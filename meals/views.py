import json
import os
from datetime import timedelta, datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from households.utils import get_current_household, get_item_suggestions, get_quantity_suggestions, merge_quantities, parse_quantity, _format_qty
from shopping.models import ShoppingItem
from .models import MealPlan, Recipe, Ingredient
from .forms import MealPlanForm, RecipeForm, IngredientForm


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
        return render(request, "choose_household.html")

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
        return render(request, "meals/choose_household.html")

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
def recipe_list(request):
    household = get_current_household(request.user)

    if not household:
        return render(request, "meals/choose_household.html")

    recipes = Recipe.objects.filter(household=household)

    return render(request, "meals/recipe_list.html", {
        "household": household,
        "recipes": recipes,
    })


@login_required
def recipe_create(request):
    household = get_current_household(request.user)

    if not household:
        return render(request, "meals/choose_household.htmls")

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

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

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

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        data = json.loads(response.choices[0].message.content)
        return JsonResponse(data)
    except Exception as e:
        from openai import RateLimitError
        if isinstance(e, RateLimitError):
            return JsonResponse({"error": "Aktuell sind keine Rezeptvorschläge verfügbar."}, status=429)
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