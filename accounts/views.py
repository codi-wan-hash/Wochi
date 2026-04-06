from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.utils import timezone

from households.utils import get_current_household
from tasks.models import Task
from meals.models import MealPlan
from shopping.models import ShoppingItem

from .forms import RegisterForm


def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("choose_household")
        
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})

        
    

@login_required
def home(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    context = {
        "household": household,
        "open_tasks_count": 0,
        "done_tasks_count": 0,
        "planned_meals_count": 0,
        "open_shopping_count": 0,
        "recent_tasks": [],
        "recent_shopping_items": [],
    }

    if household:
        today = timezone.localdate()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=13)

        open_tasks = Task.objects.filter(household=household, status="open")
        done_tasks = Task.objects.filter(household=household, status="done")
        meals_this_week = MealPlan.objects.filter(
            household=household,
            date__range=[start_of_week, end_of_week]
        )
        open_shopping = ShoppingItem.objects.filter(household=household, is_bought=False)

        context.update({
            "open_tasks_count": open_tasks.count(),
            "done_tasks_count": done_tasks.count(),
            "planned_meals_count": meals_this_week.count(),
            "open_shopping_count": open_shopping.count(),
            "recent_tasks": open_tasks.order_by("due_date")[:5],
            "recent_shopping_items": open_shopping.order_by("created_at")[:5],
        })

    return render(request, "home.html", context)