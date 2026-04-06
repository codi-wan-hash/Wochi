from datetime import timedelta, datetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from households.utils import get_current_household
from .models import MealPlan, Recipe
from .forms import MealPlanForm, RecipeForm


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

    week_plan = []
    for day in week_dates:
        week_plan.append({
            "date": day,
            "lunch": meals_by_day[day]["lunch"],
            "dinner": meals_by_day[day]["dinner"],
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
        form = MealPlanForm(
            initial={
                "date": datetime.strptime(request.GET.get("date"), "%B %d, %Y").date(),
                "meal_type": request.GET.get("meal_type"),
            },
            household=household
        )
        print("form", form.initial)

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