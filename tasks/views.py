from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from households.utils import get_current_household
from .models import Task
from .forms import TaskForm

# Erledigte Aufgaben, die die Liste höchstens zeigt. Ältere verlängern nur
# die Seite; aufräumen lässt sich mit „Erledigte löschen“.
DONE_TASKS_SHOWN = 30

# Offene Aufgaben in dieser Reihenfolge – Dringendes steht oben.
OPEN_TASK_GROUPS = (
    ("overdue", "Überfällig"),
    ("today", "Heute"),
    ("week", "Diese Woche"),
    ("later", "Später"),
)

STATUS_FILTERS = (
    ("all", "Alle"),
    ("open", "Offen"),
    ("done", "Erledigt"),
)


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _short_date(value):
    return date_format(value, "D, d.m.Y")


def group_open_tasks(tasks, today):
    """Offene Aufgaben nach Fälligkeit einteilen.

    „Diese Woche“ reicht bis Sonntag der laufenden Kalenderwoche. Leere
    Gruppen fallen weg, damit keine leeren Überschriften erscheinen.
    """
    end_of_week = today + timedelta(days=6 - today.weekday())
    buckets = {key: [] for key, _ in OPEN_TASK_GROUPS}
    for task in tasks:
        if task.due_date < today:
            buckets["overdue"].append(task)
        elif task.due_date == today:
            buckets["today"].append(task)
        elif task.due_date <= end_of_week:
            buckets["week"].append(task)
        else:
            buckets["later"].append(task)
    return [
        {"key": key, "label": label, "tasks": buckets[key]}
        for key, label in OPEN_TASK_GROUPS
        if buckets[key]
    ]


@login_required
def task_list(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    status_filter = request.GET.get("status")
    if status_filter not in dict(STATUS_FILTERS):
        status_filter = "all"

    # Zugewiesene Personen und Ersteller in einem Rutsch laden, statt pro Karte
    # eigene Abfragen auszulösen.
    tasks = (
        Task.objects.filter(household=household)
        .select_related("created_by")
        .prefetch_related("assigned_to")
    )

    groups = []
    if status_filter != "done":
        open_tasks = tasks.filter(status="open").order_by("due_date", "-created_at")
        groups = group_open_tasks(open_tasks, timezone.localdate())
    open_count = sum(len(group["tasks"]) for group in groups)

    done_tasks = []
    done_total = 0
    if status_filter != "open":
        done = tasks.filter(status="done")
        done_tasks = list(done.order_by("-due_date", "-created_at")[:DONE_TASKS_SHOWN])
        # Nur zählen, wenn es mehr gibt als angezeigt werden.
        done_total = len(done_tasks) if len(done_tasks) < DONE_TASKS_SHOWN else done.count()

    if status_filter == "done":
        empty_message = "" if done_total else "Noch keine erledigten Aufgaben."
    elif open_count:
        empty_message = ""
    elif done_total or status_filter == "open":
        empty_message = "Keine offenen Aufgaben. Was steht als Nächstes an?"
    else:
        empty_message = "Noch keine Aufgaben. Was steht an?"

    context = {
        "household": household,
        "status_filter": status_filter,
        "status_filters": STATUS_FILTERS,
        "groups": groups,
        "open_count": open_count,
        "done_tasks": done_tasks,
        "done_total": done_total,
        "empty_message": empty_message,
    }
    # ?fragment=1: nur die Listenbereiche. Das Seitenskript lädt sie nach dem
    # Abhaken neu, damit Karten in die richtige Gruppe wandern und
    # Folgeaufgaben wiederkehrender Aufgaben sofort erscheinen.
    template = "tasks/_task_sections.html" if request.GET.get("fragment") else "tasks/task_list.html"
    return render(request, template, context)


@login_required
def task_create(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    if request.method == "POST":
        form = TaskForm(request.POST, household=household)
        if form.is_valid():
            task = form.save(commit=False)
            task.household = household
            task.created_by = request.user
            task.save()
            # Bei commit=False speichert Django die Zuweisungen (M2M) nicht
            # mit – ohne save_m2m gingen sie still verloren.
            form.save_m2m()
            messages.success(request, f'Aufgabe „{task.title}“ wurde erstellt.')
            return redirect("task_list")

    else:
        form = TaskForm(household=household, initial={"due_date": timezone.localdate()})

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
            messages.success(request, "Aufgabe aktualisiert.")
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
        title = task.title
        task.delete()
        if _is_ajax(request):
            # Kein messages.success: die Meldung würde erst beim nächsten
            # Seitenaufruf erscheinen, die Karte verschwindet aber sofort.
            return JsonResponse({"deleted": True, "message": f"„{title}“ wurde gelöscht."})
        messages.success(request, "Aufgabe gelöscht.")
        return redirect("task_list")

    return render(request, "tasks/task_confirm_delete.html", {"task": task})


@login_required
@require_POST
def task_toggle_status(request, pk):
    # Nur POST: ein Statuswechsel per GET-Link ließe sich von fremden Seiten
    # auslösen und würde von Link-Vorschauen „angeklickt“.
    household = get_current_household(request.user)
    task = get_object_or_404(Task, pk=pk, household=household)

    # toggle() legt bei wiederkehrenden Aufgaben die Folgeaufgabe an (genau
    # einmal) – dieselbe Logik wie in der App.
    follow_up = task.toggle(request.user)

    if task.status == "done":
        message = f"„{task.title}“ ist erledigt."
        if follow_up:
            message += f" Nächstes Mal fällig: {_short_date(follow_up.due_date)}."
    else:
        message = f"„{task.title}“ ist wieder offen."

    if _is_ajax(request):
        return JsonResponse({
            "id": task.pk,
            "status": task.status,
            "status_display": task.get_status_display(),
            "message": message,
            "follow_up": {
                "id": follow_up.pk,
                "due_date": follow_up.due_date.isoformat(),
            } if follow_up else None,
        })
    messages.success(request, message)
    return redirect("task_list")


@login_required
@require_POST
def task_clear_done(request):
    """Alle erledigten Aufgaben des aktuellen Haushalts löschen."""
    household = get_current_household(request.user)
    if not household:
        return redirect("choose_household")

    _, deleted_per_model = Task.objects.filter(household=household, status="done").delete()
    count = deleted_per_model.get(Task._meta.label, 0)
    if count == 1:
        messages.success(request, "1 erledigte Aufgabe gelöscht.")
    elif count:
        messages.success(request, f"{count} erledigte Aufgaben gelöscht.")
    else:
        messages.info(request, "Es gab keine erledigten Aufgaben.")
    return redirect("task_list")
