from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import Household


@login_required
def choose_household(request):
    if request.user.households.exists():
        return redirect("task_list")

    error = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            name = request.POST.get("name", "").strip()
            if name:
                household = Household.objects.create(name=name)
                household.members.add(request.user)
                return redirect("task_list")

        elif action == "join":
            token = request.POST.get("invite_token", "").strip()
            if token:
                try:
                    household = Household.objects.get(invite_token=token)
                    household.members.add(request.user)
                    return redirect("task_list")
                except Household.DoesNotExist:
                    error = "Ungültiger Einladungstoken."
            else:
                error = "Bitte einen Einladungstoken eingeben."

    return render(request, "households/choose_household.html", {"error": error})