import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import HouseholdCreateForm, HouseholdJoinForm
from .models import Household, HouseholdSelection
from .utils import get_current_household, leave_household, set_current_household


def _create_or_join(request):
    """Formulare „Haushalt anlegen“ und „Beitreten“ verarbeiten.

    Gemeinsam für die Ersteinrichtung und die Haushaltsseite. Gibt
    (ergebnis, create_form, join_form) zurück; ergebnis ist "created" oder
    "joined", wenn etwas passiert ist, sonst None (dann tragen die Formulare
    ihre Fehler).
    """
    create_form = HouseholdCreateForm()
    join_form = HouseholdJoinForm()
    if request.method != "POST":
        return None, create_form, join_form

    action = request.POST.get("action")
    if action == "create":
        create_form = HouseholdCreateForm(request.POST)
        if create_form.is_valid():
            with transaction.atomic():
                household = create_form.save()
                household.members.add(request.user)
                set_current_household(request.user, household)
            messages.success(
                request,
                f"Haushalt „{household.name}“ wurde erstellt. "
                "Lade die anderen mit dem Einladungslink ein.",
            )
            return "created", create_form, join_form
    elif action == "join":
        join_form = HouseholdJoinForm(request.POST)
        if join_form.is_valid():
            household = join_form.household
            if request.user.households.filter(pk=household.pk).exists():
                messages.info(request, f"Du bist schon Mitglied von „{household.name}“.")
            else:
                household.members.add(request.user)
                messages.success(request, f"Du bist dem Haushalt „{household.name}“ beigetreten.")
            # Sonst bliebe der bisherige Haushalt aktiv und man sähe nichts
            # von dem, dem man gerade beigetreten ist.
            set_current_household(request.user, household)
            return "joined", create_form, join_form
    return None, create_form, join_form


def _member_household(request, pk):
    """Nur Haushalte, in denen der Benutzer Mitglied ist – alles andere ist 404."""
    return get_object_or_404(request.user.households, pk=pk)


@login_required
def choose_household(request):
    """Ersteinrichtung: ersten Haushalt anlegen oder einem beitreten.

    Wer schon einen Haushalt hat, landet auf der Haushaltsseite, die dieselben
    Formulare anbietet. Abgeschickte Formulare (etwa aus einem noch offenen
    Tab) werden trotzdem verarbeitet statt still verworfen.
    """
    if request.method != "POST" and request.user.households.exists():
        return redirect("household_manage")

    result, create_form, join_form = _create_or_join(request)
    if result == "created":
        # Als Nächstes die anderen einladen – der Link steht auf der Haushaltsseite.
        return redirect("household_manage")
    if result == "joined":
        return redirect("task_list")

    return render(request, "households/choose_household.html", {
        "create_form": create_form,
        "join_form": join_form,
    })


def join_via_link(request, token):
    household = get_object_or_404(Household, invite_token=token)

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    if request.user.households.filter(pk=household.pk).exists():
        # Link erneut geöffnet: zu diesem Haushalt wechseln, damit man sieht,
        # wohin der Link führt.
        set_current_household(request.user, household)
        messages.info(request, f"Du bist schon Mitglied von „{household.name}“.")
        return redirect("task_list")

    if request.method == "POST":
        household.members.add(request.user)
        set_current_household(request.user, household)
        messages.success(request, f'Du bist dem Haushalt „{household.name}“ beigetreten.')
        return redirect("task_list")

    return render(request, "households/join_via_link.html", {"household": household})


@login_required
def household_manage(request):
    """Haushalt verwalten: Mitglieder, Einladung, wechseln, verlassen sowie
    weitere Haushalte anlegen oder ihnen beitreten."""
    household = get_current_household(request.user)
    if not household:
        return redirect("choose_household")

    result, create_form, join_form = _create_or_join(request)
    if result:
        return redirect("household_manage")

    members = list(household.members.order_by("username"))
    is_last_member = len(members) == 1
    if is_last_member:
        leave_confirm = (
            f"Du bist das einzige Mitglied. Wenn du „{household.name}“ verlässt, wird der "
            "Haushalt mit allen Aufgaben, Essensplänen, Rezepten und Einkaufslisten endgültig "
            "gelöscht. Das lässt sich nicht rückgängig machen. Wirklich verlassen?"
        )
    else:
        leave_confirm = (
            f"„{household.name}“ wirklich verlassen? Zurück kommst du nur mit einem "
            "Einladungslink."
        )

    # Über pk__in statt direkt auf request.user.households zählen: dort ist die
    # Mitglieder-Verknüpfung schon auf den Benutzer gefiltert, Count ergäbe immer 1.
    other_households = (
        Household.objects.filter(pk__in=request.user.households.values("pk"))
        .exclude(pk=household.pk)
        .annotate(member_count=Count("members"))
        .order_by("name")
    )

    return render(request, "households/manage.html", {
        "household": household,
        "members": members,
        "is_last_member": is_last_member,
        "leave_confirm": leave_confirm,
        "invite_url": request.build_absolute_uri(
            reverse("join_via_link", args=[household.invite_token])
        ),
        "other_households": other_households,
        "create_form": create_form,
        "join_form": join_form,
    })


@login_required
@require_POST
def household_switch(request, pk):
    household = _member_household(request, pk)
    set_current_household(request.user, household)
    messages.success(request, f"„{household.name}“ ist jetzt dein aktiver Haushalt.")
    return redirect("household_manage")


@login_required
@require_POST
def household_leave(request, pk):
    household = _member_household(request, pk)
    name = household.name
    with transaction.atomic():
        deleted = leave_household(request.user, household)
    if deleted:
        messages.success(
            request,
            f"Du hast „{name}“ verlassen. Weil niemand mehr Mitglied war, wurde der "
            "Haushalt mit allen Daten gelöscht.",
        )
    else:
        messages.success(request, f"Du hast „{name}“ verlassen.")
    if request.user.households.exists():
        return redirect("household_manage")
    return redirect("choose_household")


@login_required
@require_POST
def household_regenerate_invite(request, pk):
    """Neuer Einladungslink – der alte funktioniert danach nicht mehr."""
    household = _member_household(request, pk)
    household.invite_token = uuid.uuid4()
    household.save(update_fields=["invite_token"])
    messages.success(
        request, "Neuer Einladungslink erstellt. Der bisherige Link funktioniert nicht mehr."
    )
    return redirect("household_manage")


@login_required
@require_POST
def household_remove_member(request, pk, user_id):
    household = _member_household(request, pk)
    if user_id == request.user.pk:
        messages.error(request, "Um selbst zu gehen, nutze „Haushalt verlassen“.")
        return redirect("household_manage")
    member = get_object_or_404(household.members, pk=user_id)
    with transaction.atomic():
        household.members.remove(member)
        # Die Auswahl „aktiver Haushalt“ der Person gleich mit aufräumen.
        HouseholdSelection.objects.filter(user=member, household=household).delete()
    messages.success(request, f"{member.username} wurde aus „{household.name}“ entfernt.")
    return redirect("household_manage")
