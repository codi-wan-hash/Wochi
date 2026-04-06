from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from households.utils import get_current_household
from .models import Task
from .forms import TaskForm

@login_required
def task_list(request):
    household = get_current_household(request.user)

    if not household:
        return render(request, "tasks/choose_household.html")
    
    tasks = Task.objects.filter(household=household)

    status_filter = request.GET.get("status")
    if status_filter in ["open", "done"]:
        tasks = tasks.filter(status=status_filter)

    return render(request, "tasks/task_list.html", {
        "tasks": tasks,
        "household": household,
        "status_filter": status_filter,
    })

@login_required
def task_create(request):
    household = get_current_household(request.user)

    if not household:
        return render(request, "tasks/choose_household.html")
    
    if request.method == "POST":
        form = TaskForm(request.POST, household=household)
        if form.is_valid():
            task = form.save(commit=False)
            task.household = household
            task.created_by = request.user
            task.save()
            return redirect("task_list")
        
    else:
        form = TaskForm(household=household)

    return render(request, "tasks/task_form.html", {
        "form": form,
        "title": "Neue Aufgabe",
    })

@login_required
def task_update(request, pk):
    household = get_current_household(request.user)
    task = get_object_or_404(Task, pk=pk, household=household)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task, household=household)
        if form.is_valid():
            form.save()
            return redirect("task_list")
    else:
        form = TaskForm(instance=task, household=household)

    return render(request, "tasks/task_form.html", {
        "form": form,
        "title": "Aufgabe bearbeiten",
    })

@login_required
def task_delete(request, pk):
    household = get_current_household(request.user)
    task = get_object_or_404(Task, pk=pk, household=household)

    if request.method == "POST":
        task.delete()
        return redirect("task_list")
    
    return render(request, "tasks/task_confirm_delete.html",  {"task": task})

@login_required
def task_toggle_status(request, pk):
    household = get_current_household(request.user)
    task = get_object_or_404(Task, pk=pk, household=household)

    task.status = "done" if task.status == "open" else "open"
    task.save()

    return redirect("task_list")
