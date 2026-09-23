import json
import logging
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from households.utils import get_current_household, get_item_suggestions, get_quantity_suggestions
from shopping.models import ShoppingItem
from shopping.services import add_ingredients, merge_quantity_text
from .ai import QUOTA_MESSAGE, ai_quota_available, openai_client
from .models import MealPlan, Recipe, Ingredient
from .forms import MealPlanForm, RecipeForm, IngredientForm, IngredientQuantityForm
from .utils import (
    MAX_INSTRUCTIONS_LENGTH,
    MAX_RECIPE_INGREDIENTS,
    clean_ingredient_list,
    cloudinary_thumbnail,
    get_ingredient_autocomplete,
    planning_range,
    scale_quantity,
)

logger = logging.getLogger(__name__)

MAX_INGREDIENTS = 30
MAX_PORTIONS = 50
# Die Eingaben des KI-Generators landen im Prompt. Ohne Grenzen ließe sich ein
# Prompt mit Megabytes Text erzeugen (Kosten, Timeouts).
MAX_INGREDIENT_LENGTH = 60
ALLOWED_FILTERS = ("vegetarisch", "vegan", "glutenfrei", "schnell")
MAX_TITLE_COLLISION_ATTEMPTS = 100
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024

# Fehlermeldungen für die Nutzer. Technische Details (Exception-Texte können
# Interna wie URLs oder Schlüssel enthalten) landen nur im Log.
AI_NOT_CONFIGURED_MESSAGE = "Die KI ist auf diesem Server nicht eingerichtet."
AI_FAILED_MESSAGE = "Die KI hat gerade nicht geantwortet. Bitte später noch einmal versuchen."
AI_UNUSABLE_MESSAGE = "KI-Antwort unbrauchbar, bitte erneut versuchen."
IMAGE_STORAGE_MISSING_MESSAGE = "Bilder können auf diesem Server nicht gespeichert werden."
IMAGE_GENERATION_FAILED_MESSAGE = "Das Bild konnte nicht erstellt werden. Bitte später noch einmal versuchen."
IMAGE_UPLOAD_FAILED_MESSAGE = "Das Bild konnte nicht gespeichert werden. Bitte später noch einmal versuchen."
CONCURRENT_SAVE_MESSAGE = "Das wurde gerade gleichzeitig geändert. Bitte die Eingaben prüfen und erneut speichern."


def get_week_dates():
    start, end = planning_range()
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _save_form(form):
    """form.save(), ohne dass ein paralleles Doppel-Absenden in HTTP 500 endet.

    clean() prüft die Eindeutigkeit. Zwei gleichzeitige Requests (Doppeltipp auf
    dem Handy) kommen aber beide durch die Prüfung, und der zweite scheitert an
    der Datenbank. Dann gibt es None und eine Meldung am Formular.
    """
    try:
        with transaction.atomic():
            return form.save()
    except IntegrityError:
        form.add_error(None, CONCURRENT_SAVE_MESSAGE)
        return None


def _first_error(form):
    """Erste Fehlermeldung eines Formulars – für die JSON-Antworten der Seiten-Skripte."""
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else None
        return f"{label}: {errors[0]}" if label else errors[0]
    return "Ungültige Eingabe."


@login_required
def meal_list(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    week_dates = get_week_dates()
    today, plan_end = week_dates[0], week_dates[-1]
    meals = list(
        MealPlan.objects.filter(household=household, date__range=(today, plan_end))
        .select_related("recipe", "assigned_to")
    )

    meals_by_day = {day: {"lunch": None, "dinner": None} for day in week_dates}
    for meal in meals:
        meals_by_day[meal.date][meal.meal_type] = meal

    start_of_next_week = today - timedelta(days=today.weekday()) + timedelta(days=7)

    week_plan = []
    for day in week_dates:
        week_plan.append({
            "date": day,
            "lunch": meals_by_day[day]["lunch"],
            "dinner": meals_by_day[day]["dinner"],
            "is_next_week_start": day == start_of_next_week,
            "is_today": day == today,
            "is_weekend": day.weekday() >= 5,
        })

    return render(request, "meals/meal_list.html", {
        "household": household,
        "week_plan": week_plan,
        # Für die Rückfrage vor "Zutaten → Einkaufsliste" (gleicher Zeitraum).
        "planned_meal_count": len(meals),
        "plan_end": plan_end,
    })


def _meal_form_context(form, household, title):
    return {
        "form": form,
        "title": title,
        # Vorschläge für das Gericht-Feld; ohne Gerichte bleibt die Liste leer.
        "recipe_titles": Recipe.objects.filter(household=household).values_list("title", flat=True),
    }


@login_required
def meal_create(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    if request.method == "POST":
        form = MealPlanForm(request.POST, household=household, user=request.user)
        if form.is_valid():
            meal = _save_form(form)
            if meal:
                if form.created_recipe:
                    messages.success(request, f'„{meal.recipe.title}“ wurde eingeplant und als neues Gericht gespeichert.')
                else:
                    messages.success(request, f'„{meal.recipe.title}“ wurde eingeplant.')
                return redirect("meal_list")
    else:
        try:
            prefill_date = date.fromisoformat(request.GET.get("date", ""))
        except ValueError:
            prefill_date = None
        form = MealPlanForm(
            initial={
                "date": prefill_date,
                "meal_type": request.GET.get("meal_type"),
            },
            household=household,
            user=request.user,
        )

    return render(request, "meals/meal_form.html", _meal_form_context(form, household, "Neue Mahlzeit planen"))


@login_required
def meal_update(request, pk):
    household = get_current_household(request.user)
    meal = get_object_or_404(MealPlan.objects.select_related("recipe"), pk=pk, household=household)

    if request.method == "POST":
        form = MealPlanForm(request.POST, instance=meal, household=household, user=request.user)
        if form.is_valid() and _save_form(form):
            messages.success(request, "Mahlzeit aktualisiert.")
            return redirect("meal_list")
    else:
        form = MealPlanForm(instance=meal, household=household, user=request.user)

    return render(request, "meals/meal_form.html", _meal_form_context(form, household, "Mahlzeit bearbeiten"))


@login_required
def meal_delete(request, pk):
    household = get_current_household(request.user)
    meal = get_object_or_404(MealPlan, pk=pk, household=household)

    if request.method == "POST":
        meal.delete()
        messages.success(request, "Mahlzeit gelöscht.")
        return redirect("meal_list")

    return render(request, "meals/meal_confirm_delete.html", {"meal": meal})


@login_required
def meal_history(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    today = timezone.localdate()
    date_to = today - timedelta(days=1)
    date_from = today - timedelta(days=14)

    meals = MealPlan.objects.filter(
        household=household,
        date__gte=date_from,
        date__lte=date_to,
    ).select_related("recipe", "assigned_to")

    meals_by_date = {}
    for meal in meals:
        meals_by_date.setdefault(meal.date, {})
        meals_by_date[meal.date][meal.meal_type] = meal

    history_days = []
    current = date_to
    while current >= date_from:
        history_days.append({
            "date": current,
            "lunch": meals_by_date.get(current, {}).get("lunch"),
            "dinner": meals_by_date.get(current, {}).get("dinner"),
            # Die Historie endet gestern; "heute" kommt hier nie vor.
            "is_yesterday": current == date_to,
            "is_weekend": current.weekday() >= 5,
        })
        current -= timedelta(days=1)

    return render(request, "meals/meal_history.html", {
        "household": household,
        "history_days": history_days,
    })


@login_required
def recipe_list(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    recipes = Recipe.objects.filter(household=household).select_related("created_by")

    return render(request, "meals/recipe_list.html", {
        "household": household,
        "recipes": recipes,
    })


@login_required
def recipe_create(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    if request.method == "POST":
        form = RecipeForm(request.POST, household=household)
        form.instance.created_by = request.user
        if form.is_valid():
            recipe = _save_form(form)
            if recipe:
                messages.success(request, f'Gericht „{recipe.title}“ wurde angelegt.')
                # Als Nächstes kommen Zutaten und Zubereitung – die stehen auf der Detailseite.
                return redirect("recipe_detail", pk=recipe.pk)
    else:
        form = RecipeForm(household=household)

    return render(request, "meals/recipe_form.html", {
        "form": form,
        "title": "Neues Gericht anlegen",
    })


@login_required
def recipe_update(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method == "POST":
        form = RecipeForm(request.POST, instance=recipe, household=household)
        if form.is_valid() and _save_form(form):
            messages.success(request, "Gericht aktualisiert.")
            return redirect("recipe_list")
    else:
        form = RecipeForm(instance=recipe, household=household)

    return render(request, "meals/recipe_form.html", {
        "form": form,
        "title": "Gericht bearbeiten",
        "recipe": recipe,
    })


@login_required
def recipe_delete(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method == "POST":
        _, deleted = recipe.delete()
        removed_meals = deleted.get(MealPlan._meta.label, 0)
        if removed_meals:
            plural = "en" if removed_meals != 1 else ""
            messages.success(request, f"Gericht gelöscht, dazu {removed_meals} geplante Mahlzeit{plural}.")
        else:
            messages.success(request, "Gericht gelöscht.")
        return redirect("recipe_list")

    # MealPlan.recipe löscht per CASCADE mit – das muss vor dem Bestätigen sichtbar sein.
    counts = recipe.planned_meals.aggregate(
        total=Count("pk"),
        upcoming=Count("pk", filter=Q(date__gte=timezone.localdate())),
    )
    return render(request, "meals/recipe_confirm_delete.html", {
        "recipe": recipe,
        "planned_meal_count": counts["total"],
        "upcoming_meal_count": counts["upcoming"],
    })


@login_required
def recipe_detail(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)
    form = IngredientForm()
    return render(request, "meals/recipe_detail.html", {
        "recipe": recipe,
        "form": form,
        "suggestions": get_item_suggestions(household),
        "quantity_suggestions": get_quantity_suggestions(household),
    })


def _ingredient_json(ingredient):
    """Zutat für die Seiten-Skripte, inkl. der URLs für ihre Aktionen."""
    return {
        "id": ingredient.pk,
        "name": ingredient.name,
        "quantity": ingredient.quantity,
        "scale_url": reverse("ingredient_scale", args=[ingredient.pk]),
        "shopping_url": reverse("ingredient_to_shopping", args=[ingredient.pk]),
        "delete_url": reverse("ingredient_delete", args=[ingredient.pk]),
    }


@login_required
def ingredient_add(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        form = IngredientForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"].strip()
            quantity = form.cleaned_data["quantity"].strip()
            existing = recipe.ingredients.filter(name__iexact=name).first()
            if existing:
                existing.quantity = merge_quantity_text(existing.quantity, quantity)
                existing.save()
                ingredient = existing
                merged = True
            else:
                ingredient = form.save(commit=False)
                ingredient.recipe = recipe
                ingredient.save()
                merged = False
            if is_ajax:
                return JsonResponse({**_ingredient_json(ingredient), "merged": merged})
        elif is_ajax:
            return JsonResponse({"error": _first_error(form)}, status=400)
    return redirect("recipe_detail", pk=pk)


@login_required
def ingredient_delete(request, pk):
    household = get_current_household(request.user)
    ingredient = get_object_or_404(Ingredient, pk=pk, recipe__household=household)

    if request.method == "POST":
        ingredient.delete()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"deleted": True})
    return redirect("recipe_detail", pk=ingredient.recipe.pk)


@login_required
@require_POST
def ingredient_scale(request, pk):
    """Menge einer Zutat ändern; mit scale_all=1 alle Mengen im gleichen Verhältnis."""
    household = get_current_household(request.user)
    ingredient = get_object_or_404(
        Ingredient.objects.select_related("recipe"), pk=pk, recipe__household=household
    )

    form = IngredientQuantityForm(request.POST, instance=ingredient)
    if not form.is_valid():
        return JsonResponse({"error": _first_error(form)}, status=400)

    with transaction.atomic():
        ingredient = form.save()
        updated = [ingredient]
        if form.factor is not None:
            scaled = []
            for other in ingredient.recipe.ingredients.exclude(pk=ingredient.pk):
                new_quantity = scale_quantity(other.quantity, form.factor)
                if new_quantity is not None and new_quantity != other.quantity:
                    other.quantity = new_quantity
                    scaled.append(other)
            Ingredient.objects.bulk_update(scaled, ["quantity"])
            updated += scaled

    return JsonResponse({
        "status": "scaled" if form.factor is not None else "updated",
        "ingredients": [{"id": ing.pk, "quantity": ing.quantity} for ing in updated],
    })


@login_required
def ingredient_to_shopping(request, pk):
    household = get_current_household(request.user)
    ingredient = get_object_or_404(Ingredient, pk=pk, recipe__household=household)

    if request.method == "POST":
        existing = ShoppingItem.objects.filter(
            household=household,
            name__iexact=ingredient.name,
            is_bought=False,
        ).first()

        if existing:
            return JsonResponse({
                "status": "duplicate",
                "existing_id": existing.pk,
                "existing_quantity": existing.quantity,
                "new_quantity": ingredient.quantity,
                "name": ingredient.name,
                "merge_url": reverse("shopping_merge_quantity", args=[existing.pk]),
            })

        ShoppingItem.objects.create(
            household=household,
            name=ingredient.name,
            quantity=ingredient.quantity,
            added_by=request.user,
        )
        return JsonResponse({"status": "added"})

    return redirect("recipe_detail", pk=ingredient.recipe.pk)


@login_required
def recipe_all_to_shopping(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method != "POST":
        return redirect("recipe_detail", pk=pk)

    with transaction.atomic():
        added, merged = add_ingredients(
            household, request.user, recipe.ingredients.values_list("name", "quantity")
        )
    return JsonResponse({"added": added, "merged": merged})


@login_required
def meals_week_to_shopping(request):
    household = get_current_household(request.user)
    if not household:
        return JsonResponse({"error": "Kein Haushalt"}, status=400)

    if request.method != "POST":
        return redirect("meal_list")

    # Gleicher Zeitraum wie die Planungsansicht: heute bis Sonntag nächster
    # Woche. Schon gegessene Tage gehören nicht mehr auf die Einkaufsliste.
    date_from, date_to = planning_range()
    meals = list(
        MealPlan.objects.filter(household=household, date__range=(date_from, date_to))
        .select_related("recipe")
        .prefetch_related("recipe__ingredients")
    )
    ingredients = [
        (ingredient.name, ingredient.quantity)
        for meal in meals
        for ingredient in meal.recipe.ingredients.all()
    ]
    with transaction.atomic():
        added, merged = add_ingredients(household, request.user, ingredients)
    return JsonResponse({"added": added, "merged": merged, "meals": len(meals)})


def _ask_ai_for_json(prompt):
    """Fragt das Sprachmodell und gibt die JSON-Antwort als Python-Objekt zurück.

    Wirft bei jedem Fehler (Netz, Timeout, Ratenlimit, kaputtes JSON); die Views
    loggen ihn und antworten mit einer allgemeinen Meldung.
    """
    response = openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    return json.loads(response.choices[0].message.content)


def _raw_suggestions(data):
    """Die (höchstens drei) Vorschlags-Dicts aus einer KI-Antwort."""
    suggestions = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(suggestions, list):
        return []
    return [s for s in suggestions[:3] if isinstance(s, dict)]


def _minutes(value):
    """Zubereitungszeit als ganze Minuten (1–1440) oder None."""
    try:
        minutes = int(value)
    except (TypeError, ValueError, OverflowError):  # OverflowError: JSON erlaubt Infinity
        return None
    return minutes if 1 <= minutes <= 24 * 60 else None


@login_required
def recipe_ai_suggest(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    if not settings.OPENAI_API_KEY:
        return JsonResponse({"error": AI_NOT_CONFIGURED_MESSAGE}, status=503)
    if not ai_quota_available(request.user, "text"):
        return JsonResponse({"error": QUOTA_MESSAGE}, status=429)

    prompt = f"""Du bist ein Kochassistent. Erstelle genau 3 verschiedene Rezeptvarianten für das Gericht "{recipe.title}".
Antworte ausschließlich mit folgendem JSON:
{{
  "suggestions": [
    {{
      "variant": "kurze Beschreibung der Variante (max 8 Wörter)",
      "ingredients": [{{"name": "Zutat", "quantity": "Menge"}}],
      "instructions": "Nummerierte Schritt-für-Schritt Zubereitung"
    }}
  ]
}}"""

    try:
        data = _ask_ai_for_json(prompt)
    except Exception:
        logger.exception("KI-Rezeptvarianten für Gericht %s fehlgeschlagen", recipe.pk)
        return JsonResponse({"error": AI_FAILED_MESSAGE}, status=502)

    # Nur geprüfte, gekürzte Felder weitergeben – die Seite rendert sie direkt.
    suggestions = []
    for raw in _raw_suggestions(data):
        ingredients = clean_ingredient_list(raw.get("ingredients"))
        instructions = str(raw.get("instructions") or "").strip()[:MAX_INSTRUCTIONS_LENGTH]
        if ingredients and instructions:
            suggestions.append({
                "variant": str(raw.get("variant") or "").strip()[:200],
                "ingredients": ingredients,
                "instructions": instructions,
            })
    if not suggestions:
        return JsonResponse({"error": AI_UNUSABLE_MESSAGE}, status=502)
    return JsonResponse({"suggestions": suggestions})


def _image_json(recipe):
    return {"image_url": recipe.image, "thumb_url": cloudinary_thumbnail(recipe.image)}


def _store_recipe_image(recipe, source):
    """Bild (Datei oder data-URI) bei Cloudinary ablegen und am Gericht speichern."""
    import cloudinary.uploader

    result = cloudinary.uploader.upload(
        source,
        folder="wochi/recipes",
        public_id=f"recipe_{recipe.pk}",
        overwrite=True,
    )
    recipe.image = result["secure_url"]
    recipe.save(update_fields=["image"])


def _generate_and_store_recipe_image(recipe):
    response = openai_client().images.generate(
        model="gpt-image-1",
        prompt=(
            f"Professional food photography of '{recipe.title}', restaurant quality dish, "
            "warm natural lighting, overhead shot on a wooden table, minimal props, "
            "clean background, appetizing presentation"
        ),
        size="1024x1024",
        quality="medium",
        n=1,
    )
    # gpt-image-1 returns base64-encoded image data, not a URL.
    b64_data = response.data[0].b64_json
    _store_recipe_image(recipe, f"data:image/png;base64,{b64_data}")


@login_required
def recipe_generate_image(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)
    if not settings.OPENAI_API_KEY:
        return JsonResponse({"error": AI_NOT_CONFIGURED_MESSAGE}, status=503)
    # Vor dem kostenpflichtigen Generieren prüfen, ob sich das Bild überhaupt speichern lässt.
    if not getattr(settings, "CLOUDINARY_URL", ""):
        return JsonResponse({"error": IMAGE_STORAGE_MISSING_MESSAGE}, status=503)
    if not ai_quota_available(request.user, "image"):
        return JsonResponse({"error": QUOTA_MESSAGE}, status=429)
    try:
        _generate_and_store_recipe_image(recipe)
    except Exception:
        logger.exception("Bildgenerierung für Gericht %s fehlgeschlagen", recipe.pk)
        return JsonResponse({"error": IMAGE_GENERATION_FAILED_MESSAGE}, status=502)
    return JsonResponse(_image_json(recipe))


@login_required
def recipe_upload_image(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)
    file = request.FILES.get("image")
    if not file:
        return JsonResponse({"error": "Keine Datei übermittelt."}, status=400)
    if not (file.content_type or "").startswith("image/"):
        return JsonResponse({"error": "Bitte ein Bild auswählen (z. B. JPG oder PNG)."}, status=400)
    if file.size > MAX_IMAGE_UPLOAD_BYTES:
        return JsonResponse({"error": "Das Bild ist zu groß (höchstens 10 MB)."}, status=400)
    if not getattr(settings, "CLOUDINARY_URL", ""):
        return JsonResponse({"error": IMAGE_STORAGE_MISSING_MESSAGE}, status=503)
    try:
        _store_recipe_image(recipe, file)
    except Exception:
        logger.exception("Bild-Upload für Gericht %s fehlgeschlagen", recipe.pk)
        return JsonResponse({"error": IMAGE_UPLOAD_FAILED_MESSAGE}, status=502)
    return JsonResponse(_image_json(recipe))


@login_required
def recipe_apply_suggestion(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Ungültige Daten."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Ungültige Daten."}, status=400)

    instructions = data.get("instructions") or ""
    ingredients = data.get("ingredients") or []
    if not isinstance(instructions, str):
        return JsonResponse({"error": "Ungültige Daten."}, status=400)
    if len(instructions) > MAX_INSTRUCTIONS_LENGTH:
        return JsonResponse(
            {"error": f"Die Zubereitung ist zu lang (höchstens {MAX_INSTRUCTIONS_LENGTH} Zeichen)."},
            status=400,
        )
    if not isinstance(ingredients, list) or len(ingredients) > MAX_RECIPE_INGREDIENTS:
        return JsonResponse({"error": f"Höchstens {MAX_RECIPE_INGREDIENTS} Zutaten."}, status=400)

    # Alles oder nichts: scheitert das Anlegen, bleiben die alten Zutaten erhalten.
    with transaction.atomic():
        recipe.instructions = instructions
        recipe.save(update_fields=["instructions"])
        if not data.get("save_instructions_only"):
            recipe.ingredients.all().delete()
            Ingredient.objects.bulk_create([
                Ingredient(recipe=recipe, name=ing["name"], quantity=ing["quantity"])
                for ing in clean_ingredient_list(ingredients)
            ])
    return JsonResponse({"success": True})


@login_required
def ai_generator_form(request):
    household = get_current_household(request.user)
    if not household:
        return redirect("choose_household")
    return render(request, "meals/ai_generator.html", {
        "household": household,
        "autocomplete": get_ingredient_autocomplete(household),
        "default_portions": max(household.members.count(), 2),
    })


@login_required
def ai_generator_suggest(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)

    raw_ingredients = payload.get("ingredients") or []
    if not isinstance(raw_ingredients, list):
        return JsonResponse({"error": "Ungültige Zutatenliste."}, status=400)
    ingredients = [
        str(x).strip()[:MAX_INGREDIENT_LENGTH].strip()
        for x in raw_ingredients if str(x).strip()
    ]
    if not ingredients:
        return JsonResponse({"error": "Mindestens 1 Zutat angeben."}, status=400)
    if len(ingredients) > MAX_INGREDIENTS:
        return JsonResponse({"error": "Maximal 30 Zutaten."}, status=400)

    try:
        raw_portions = payload.get("portions")
        portions = int(raw_portions if raw_portions is not None else 2)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Portionen müssen eine Zahl sein."}, status=400)
    if not (1 <= portions <= MAX_PORTIONS):
        return JsonResponse({"error": "Portionen müssen zwischen 1 und 50 liegen."}, status=400)

    # Nur bekannte Filter; alles andere würde ungeprüft im Prompt landen.
    raw_filters = payload.get("filters") or []
    requested = {str(f).strip().lower() for f in raw_filters} if isinstance(raw_filters, list) else set()
    filters = [f for f in ALLOWED_FILTERS if f in requested]

    if not getattr(settings, "OPENAI_API_KEY", ""):
        return JsonResponse({"error": AI_NOT_CONFIGURED_MESSAGE}, status=503)
    if not ai_quota_available(request.user, "text"):
        return JsonResponse({"error": QUOTA_MESSAGE}, status=429)

    ingredients_csv = ", ".join(ingredients)
    filter_csv = ", ".join(filters) if filters else "keine"
    prompt = (
        f"Du bist Kochassistent. User hat folgende Zutaten zur Verfügung: {ingredients_csv}.\n"
        f"Erstelle genau 3 verschiedene Rezeptvorschläge für {portions} Portion(en).\n"
        f"Filter (falls aktiv): {filter_csv}.\n\n"
        "Regeln:\n"
        "- Nutze möglichst nur die genannten Zutaten. Übliche Pantry-Items (Salz, Pfeffer, Öl, Wasser) darfst du ergänzen.\n"
        "- Bei Filter 'vegetarisch': kein Fleisch/Fisch.\n"
        "- Bei Filter 'vegan': zusätzlich keine tierischen Produkte.\n"
        "- Bei Filter 'glutenfrei': kein Weizen/Roggen/Gerste.\n"
        "- Bei Filter 'schnell': Zubereitung max 30 Minuten.\n\n"
        "Antworte ausschließlich mit folgendem JSON:\n"
        "{\n"
        '  "suggestions": [\n'
        '    {\n'
        '      "title": "Kurzer prägnanter Rezeptname",\n'
        '      "duration_min": 25,\n'
        '      "ingredients": [{"name": "Hähnchenbrust", "quantity": "300g"}],\n'
        '      "instructions": "1. Reis aufsetzen.\\n2. ..."\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "Genau 3 Vorschläge. Mengen in deutscher Notation (g, ml, EL, TL, Stück)."
    )

    try:
        data = _ask_ai_for_json(prompt)
    except Exception:
        logger.exception("KI-Rezeptgenerator fehlgeschlagen")
        return JsonResponse({"error": AI_FAILED_MESSAGE}, status=502)

    suggestions = []
    for raw in _raw_suggestions(data):
        title = str(raw.get("title") or "").strip()[:200]
        instructions = str(raw.get("instructions") or "").strip()[:MAX_INSTRUCTIONS_LENGTH]
        if not (title and instructions and isinstance(raw.get("ingredients"), list)):
            return JsonResponse({"error": AI_UNUSABLE_MESSAGE}, status=502)
        suggestions.append({
            "title": title,
            "duration_min": _minutes(raw.get("duration_min")),
            "ingredients": clean_ingredient_list(raw.get("ingredients")),
            "instructions": instructions,
        })
    if len(suggestions) != 3:
        return JsonResponse({"error": AI_UNUSABLE_MESSAGE}, status=502)

    return JsonResponse({"suggestions": suggestions})


def _numbered_title(title, number):
    """"Titel (2)" usw. – gekürzt, damit Name und Zusatz in 200 Zeichen passen."""
    if number == 1:
        return title
    suffix = f" ({number})"
    return title[:200 - len(suffix)] + suffix


def _create_recipe_with_free_title(household, title, **fields):
    """Legt das Gericht an; ist der Name vergeben, mit "(2)", "(3)", … dahinter.

    Wie im Formular zählt Groß-/Kleinschreibung nicht als Unterschied.
    Gibt None zurück, wenn kein freier Name gefunden wurde.
    """
    for number in range(1, MAX_TITLE_COLLISION_ATTEMPTS + 1):
        candidate = _numbered_title(title, number)
        if Recipe.objects.filter(household=household, title__iexact=candidate).exists():
            continue
        try:
            with transaction.atomic():
                return Recipe.objects.create(household=household, title=candidate, **fields)
        except IntegrityError:
            # Gerade parallel unter diesem Namen angelegt – nächste Nummer.
            continue
    return None


@login_required
def ai_generator_save(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    household = get_current_household(request.user)
    if not household:
        return JsonResponse({"error": "Kein Haushalt aktiv."}, status=400)

    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)

    # Die Werte stammen aus der KI-Antwort (über den Browser) – Typen und
    # Längen sind nicht garantiert, z. B. Mengen als Zahl.
    title = str(payload.get("title") or "").strip()[:200]
    if not title:
        return JsonResponse({"error": "Titel fehlt."}, status=400)

    raw_ingredients = payload.get("ingredients") or []
    if not isinstance(raw_ingredients, list) or len(raw_ingredients) > MAX_RECIPE_INGREDIENTS:
        return JsonResponse({"error": "Ungültige Zutatenliste."}, status=400)

    instructions = str(payload.get("instructions") or "").strip()[:MAX_INSTRUCTIONS_LENGTH]
    duration_min = _minutes(payload.get("duration_min"))
    notes_bits = []
    if duration_min:
        notes_bits.append(f"~{duration_min} min")
    notes_bits.append("per KI generiert")
    notes = " · ".join(notes_bits)

    with transaction.atomic():
        recipe = _create_recipe_with_free_title(
            household, title, notes=notes, instructions=instructions, created_by=request.user
        )
        if recipe is not None:
            Ingredient.objects.bulk_create([
                Ingredient(recipe=recipe, name=ing["name"], quantity=ing["quantity"])
                for ing in clean_ingredient_list(raw_ingredients)
            ])
    if recipe is None:
        return JsonResponse({"error": "Konnte keinen eindeutigen Titel finden."}, status=409)

    return JsonResponse({
        "recipe_id": recipe.pk,
        "redirect_url": reverse("recipe_detail", args=[recipe.pk]),
    })
