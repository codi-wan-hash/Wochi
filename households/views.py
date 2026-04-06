from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import Household


@login_required
def choose_household(request):
    if request.user.households.exists():
        return redirect("task_list")

    households = Household.objects.all()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            name = request.POST.get("name")
            if name:
                household = Household.objects.create(name=name)
                household.members.add(request.user)
                return redirect("task_list")

        elif action == "join":
            household_id = request.POST.get("household_id")
            if household_id:
                household = get_object_or_404(Household, id=household_id)
                household.members.add(request.user)
                return redirect("task_list")

    return render(request, "households/choose_household.html", {
        "households": households,
    })