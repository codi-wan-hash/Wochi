import json
import os
from datetime import timedelta, datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from openai import OpenAI, RateLimitError

from households.utils import get_current_household, get_item_suggestions, get_quantity_suggestions, merge_quantities, parse_quantity, _format_qty
from shopping.models import ShoppingItem
from .models import MealPlan, Recipe, Ingredient
from .forms import MealPlanForm, RecipeForm, IngredientForm

MAX_INGREDIENTS = 30
MAX_PORTIONS = 50


def get_week_dates():
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday()) # monday
    end_of_next_week = start_of_week + timedelta(days=13) # sunday next week

    week_dates = []
    current_day = today
    
    while current_day <= end_of_next_week:
        week_dates.append(current_day)
        current_day += timedelta(days=1)

    return week_dates


@login_required
def meal_list(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    week_dates = get_week_dates()
    meals = MealPlan.objects.filter(household=household, date__in=week_dates)

    meals_by_day = {day: {"lunch": None, "dinner": None} for day in week_dates}
    for meal in meals:
        meals_by_day[meal.date][meal.meal_type] = meal

    today = timezone.localdate()
    start_of_next_week = today - timedelta(days=today.weekday()) + timedelta(days=7)

    week_plan = []
    for day in week_dates:
        week_plan.append({
            "date": day,
            "lunch": meals_by_day[day]["lunch"],
            "dinner": meals_by_day[day]["dinner"],
            "is_next_week_start": day == start_of_next_week,
        })

    return render(request, "meals/meal_list.html", {
        "household": household,
        "week_plan": week_plan,
    })


@login_required
def meal_create(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    if request.method == "POST":
        form = MealPlanForm(request.POST, household=household)
        if form.is_valid():
            meal = form.save(commit=False)
            meal.household = household
            meal.save()
            return redirect("meal_list")
    else:
        from datetime import date as date_type
        try:
            prefill_date = date_type.fromisoformat(request.GET.get("date", ""))
        except ValueError:
            prefill_date = None
        form = MealPlanForm(
            initial={
                "date": prefill_date,
                "meal_type": request.GET.get("meal_type"),
            },
            household=household
        )

    return render(request, "meals/meal_form.html", {
        "form": form,
        "title": "Neue Mahlzeit planen",
    })


@login_required
def meal_update(request, pk):
    household = get_current_household(request.user)
    meal = get_object_or_404(MealPlan, pk=pk, household=household)

    if request.method == "POST":
        form = MealPlanForm(request.POST, instance=meal, household=household)
        if form.is_valid():
            form.save()
            return redirect("meal_list")
    else:
        form = MealPlanForm(instance=meal, household=household)

    return render(request, "meals/meal_form.html", {
        "form": form,
        "title": "Mahlzeit bearbeiten",
    })


@login_required
def meal_delete(request, pk):
    household = get_current_household(request.user)
    meal = get_object_or_404(MealPlan, pk=pk, household=household)

    if request.method == "POST":
        meal.delete()
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

    recipes = Recipe.objects.filter(household=household)

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
        form = RecipeForm(request.POST)
        if form.is_valid():
            recipe = form.save(commit=False)
            recipe.household = household
            recipe.created_by = request.user
            recipe.save()
            return redirect("recipe_list")
    else:
        form = RecipeForm()

    return render(request, "meals/recipe_form.html", {
        "form": form,
        "title": "Neues Gericht anlegen",
    })


@login_required
def recipe_update(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method == "POST":
        form = RecipeForm(request.POST, instance=recipe)
        if form.is_valid():
            form.save()
            return redirect("recipe_list")
    else:
        form = RecipeForm(instance=recipe)

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
        recipe.delete()
        return redirect("recipe_list")

    return render(request, "meals/recipe_confirm_delete.html", {"recipe": recipe})


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


@login_required
def ingredient_add(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method == "POST":
        form = IngredientForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"].strip()
            quantity = form.cleaned_data["quantity"].strip()
            existing = recipe.ingredients.filter(name__iexact=name).first()
            if existing:
                existing.quantity = merge_quantities(existing.quantity, quantity)
                existing.save()
                ingredient = existing
                merged = True
            else:
                ingredient = form.save(commit=False)
                ingredient.recipe = recipe
                ingredient.save()
                merged = False
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({
                    "id": ingredient.pk,
                    "name": ingredient.name,
                    "quantity": ingredient.quantity,
                    "merged": merged,
                })
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
def ingredient_scale(request, pk):
    household = get_current_household(request.user)
    ingredient = get_object_or_404(Ingredient, pk=pk, recipe__household=household)

    if request.method == "POST":
        new_quantity = request.POST.get("quantity", "").strip()
        old_quantity = ingredient.quantity

        p_old = parse_quantity(old_quantity)
        p_new = parse_quantity(new_quantity)

        ingredient.quantity = new_quantity
        ingredient.save()

        updated = [{"id": ingredient.pk, "quantity": new_quantity}]

        if p_old and p_new and p_old[0] > 0:
            ratio = p_new[0] / p_old[0]
            for ing in ingredient.recipe.ingredients.exclude(pk=ingredient.pk):
                p = parse_quantity(ing.quantity)
                if p:
                    scaled = p[0] * ratio
                    scaled = int(scaled) if scaled == int(scaled) else round(scaled, 2)
                    ing.quantity = _format_qty(scaled, p[1])
                    ing.save()
                updated.append({"id": ing.pk, "quantity": ing.quantity})

        return JsonResponse({"status": "scaled", "ingredients": updated})

    return JsonResponse({"error": "invalid"}, status=400)


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

    added, merged = 0, 0
    for ingredient in recipe.ingredients.all():
        existing = ShoppingItem.objects.filter(
            household=household, name__iexact=ingredient.name, is_bought=False
        ).first()
        if existing:
            existing.quantity = merge_quantities(existing.quantity, ingredient.quantity)
            existing.save()
            merged += 1
        else:
            ShoppingItem.objects.create(
                household=household,
                name=ingredient.name,
                quantity=ingredient.quantity,
                added_by=request.user,
            )
            added += 1
    return JsonResponse({"added": added, "merged": merged})


@login_required
def meals_week_to_shopping(request):
    household = get_current_household(request.user)
    if not household:
        return JsonResponse({"error": "Kein Haushalt"}, status=400)

    if request.method != "POST":
        return redirect("meal_list")

    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=(today.weekday()))
    date_from = monday
    date_to = monday + timedelta(days=13)

    meals = MealPlan.objects.filter(
        household=household, date__gte=date_from, date__lte=date_to,
    ).select_related("recipe").prefetch_related("recipe__ingredients")

    added, merged = 0, 0
    for meal in meals:
        for ingredient in meal.recipe.ingredients.all():
            existing = ShoppingItem.objects.filter(
                household=household, name__iexact=ingredient.name, is_bought=False
            ).first()
            if existing:
                existing.quantity = merge_quantities(existing.quantity, ingredient.quantity)
                existing.save()
                merged += 1
            else:
                ShoppingItem.objects.create(
                    household=household,
                    name=ingredient.name,
                    quantity=ingredient.quantity,
                    added_by=request.user,
                )
                added += 1
    return JsonResponse({"added": added, "merged": merged})


@login_required
def shopping_merge_quantity(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    if request.method == "POST":
        extra = request.POST.get("extra_quantity", "").strip()
        if extra:
            item.quantity = merge_quantities(item.quantity, extra)
        item.save()
        return JsonResponse({"status": "merged", "new_quantity": item.quantity})

    return redirect("shopping_list")


@login_required
def recipe_ai_suggest(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return JsonResponse({"error": "Kein OpenAI API-Key konfiguriert. Bitte OPENAI_API_KEY als Umgebungsvariable setzen."}, status=503)

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
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        data = json.loads(response.choices[0].message.content)
        return JsonResponse(data)
    except RateLimitError:
        return JsonResponse({"error": "Aktuell sind keine Rezeptvorschläge verfügbar."}, status=429)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def _generate_and_store_recipe_image(recipe):
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.images.generate(
        model="dall-e-3",
        prompt=(
            f"Professional food photography of '{recipe.title}', restaurant quality dish, "
            "warm natural lighting, overhead shot on a wooden table, minimal props, "
            "clean background, appetizing presentation"
        ),
        size="1024x1024",
        quality="standard",
        n=1,
    )
    dalle_url = response.data[0].url

    cloudinary_url = getattr(settings, "CLOUDINARY_URL", "")
    if cloudinary_url:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            dalle_url,
            folder="wochi/recipes",
            public_id=f"recipe_{recipe.pk}",
            overwrite=True,
        )
        recipe.image = result["secure_url"]
    else:
        recipe.image = dalle_url

    recipe.save(update_fields=["image"])


@login_required
def recipe_generate_image(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)
    if not settings.OPENAI_API_KEY:
        return JsonResponse({"error": "Kein OpenAI API-Key konfiguriert."}, status=503)
    try:
        _generate_and_store_recipe_image(recipe)
        return JsonResponse({"image_url": recipe.image})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def recipe_upload_image(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)
    file = request.FILES.get("image")
    if not file:
        return JsonResponse({"error": "Keine Datei übermittelt."}, status=400)
    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            file,
            folder="wochi/recipes",
            public_id=f"recipe_{recipe.pk}",
            overwrite=True,
        )
        recipe.image = result["secure_url"]
        recipe.save(update_fields=["image"])
        return JsonResponse({"image_url": recipe.image})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def recipe_apply_suggestion(request, pk):
    household = get_current_household(request.user)
    recipe = get_object_or_404(Recipe, pk=pk, household=household)

    if request.method == "POST":
        data = json.loads(request.body)
        recipe.instructions = data.get("instructions", "")
        recipe.save()

        if not data.get("save_instructions_only"):
            recipe.ingredients.all().delete()
            for ing in data.get("ingredients") or []:
                name = ing.get("name", "").strip()
                if name:
                    Ingredient.objects.create(
                        recipe=recipe,
                        name=name,
                        quantity=ing.get("quantity", ""),
                    )
        return JsonResponse({"success": True})

    return JsonResponse({"error": "POST required"}, status=405)


@login_required
def ai_generator_form(request):
    household = get_current_household(request.user)
    if not household:
        return redirect("choose_household")
    from .utils import get_ingredient_autocomplete
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
    except json.JSONDecodeError:
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)

    ingredients = [str(x).strip() for x in (payload.get("ingredients") or []) if str(x).strip()]
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

    filters = [str(f).strip().lower() for f in (payload.get("filters") or []) if str(f).strip()]

    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        return JsonResponse({"error": "Kein OpenAI API-Key konfiguriert."}, status=503)

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
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        raw = response.choices[0].message.content
    except RateLimitError:
        return JsonResponse({"error": "Aktuell sind keine Rezeptvorschläge verfügbar."}, status=429)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return JsonResponse({"error": "AI-Antwort unbrauchbar, bitte erneut versuchen."}, status=502)

    suggestions = data.get("suggestions") or []
    if len(suggestions) != 3:
        return JsonResponse({"error": "AI-Antwort unbrauchbar, bitte erneut versuchen."}, status=502)
    for s in suggestions:
        if not (s.get("title") and isinstance(s.get("ingredients"), list) and s.get("instructions")):
            return JsonResponse({"error": "AI-Antwort unbrauchbar, bitte erneut versuchen."}, status=502)

    return JsonResponse({"suggestions": suggestions})


@login_required
def ai_generator_save(request):
    return JsonResponse({"error": "not implemented yet"}, status=501)