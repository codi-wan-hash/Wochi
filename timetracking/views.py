from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import UserProfileForm, WorkEntryForm
from .models import WorkEntry
from .utils import (
    calculate_total_saldo,
    get_holiday_name,
    get_or_create_profile,
    get_soll_days_in_range,
)


@login_required
def settings_view(request):
    profile = get_or_create_profile(request.user)
    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Einstellungen gespeichert.")
            if profile.timetracking_enabled:
                return redirect("timetracking:dashboard")
            return redirect("timetracking:settings_view")
    else:
        form = UserProfileForm(instance=profile)
    return render(request, "timetracking/settings.html", {"form": form, "profile": profile})


@login_required
def dashboard(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    today = date.today()

    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]
    entries_this_week = {
        e.date: e
        for e in WorkEntry.objects.filter(
            user=request.user, date__range=[week_days[0], week_days[-1]]
        )
    }

    week_data = []
    for day in week_days:
        entry = entries_this_week.get(day)
        holiday_name = get_holiday_name(day, profile.bundesland)
        is_weekend = day.weekday() >= 5
        is_soll = not is_weekend and not holiday_name
        soll = profile.daily_target_hours if is_soll else Decimal("0")

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = profile.daily_target_hours
        else:
            ist = Decimal("0")

        pending = day == today and not entry and is_soll
        week_data.append({
            "day": day,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "soll": soll,
            "ist": ist,
            "diff": Decimal("0") if pending else ist - soll,
            "pending": pending,
        })

    first_of_month = today.replace(day=1)
    _, days_in_month = monthrange(today.year, today.month)
    last_of_month = today.replace(day=days_in_month)
    month_soll_days = get_soll_days_in_range(first_of_month, last_of_month, profile.bundesland)
    month_soll = Decimal(str(len(month_soll_days))) * profile.daily_target_hours

    entries_this_month = WorkEntry.objects.filter(
        user=request.user, date__year=today.year, date__month=today.month
    )
    month_ist = Decimal("0")
    for e in entries_this_month:
        if e.entry_type == "work":
            month_ist += Decimal(str(e.worked_hours or 0))
        else:
            month_ist += profile.daily_target_hours

    total_saldo = calculate_total_saldo(request.user)

    prev_month_first = (first_of_month - timedelta(days=1)).replace(day=1)
    next_month_first = last_of_month + timedelta(days=1)

    return render(request, "timetracking/dashboard.html", {
        "profile": profile,
        "today": today,
        "week_data": week_data,
        "month_soll_days": len(month_soll_days),
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
        "total_saldo": total_saldo,
        "prev_month": prev_month_first,
        "next_month": next_month_first,
    })


@login_required
def entry_create(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    initial = {}
    date_str = request.GET.get("date")
    if date_str:
        try:
            initial["date"] = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    if request.method == "POST":
        form = WorkEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Eintrag gespeichert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(initial=initial)

    return render(request, "timetracking/entry_form.html", {"form": form, "title": "Neuer Eintrag"})


@login_required
def entry_edit(request, pk):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    entry = get_object_or_404(WorkEntry, pk=pk, user=request.user)

    if request.method == "POST":
        form = WorkEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            messages.success(request, "Eintrag aktualisiert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(instance=entry)

    return render(request, "timetracking/entry_form.html", {"form": form, "title": "Eintrag bearbeiten"})


@login_required
def entry_delete(request, pk):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    entry = get_object_or_404(WorkEntry, pk=pk, user=request.user)

    if request.method == "POST":
        entry.delete()
        messages.success(request, "Eintrag gelöscht.")
        return redirect("timetracking:dashboard")

    return render(request, "timetracking/entry_confirm_delete.html", {"entry": entry})


@login_required
def month_detail(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    entries = {
        e.date: e
        for e in WorkEntry.objects.filter(user=request.user, date__range=[first_day, last_day])
    }

    days_data = []
    for i in range(1, days_in_month + 1):
        d = date(year, month, i)
        entry = entries.get(d)
        holiday_name = get_holiday_name(d, profile.bundesland)
        is_weekend = d.weekday() >= 5
        is_soll = not is_weekend and not holiday_name
        soll = profile.daily_target_hours if is_soll else Decimal("0")

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = profile.daily_target_hours
        else:
            ist = Decimal("0")

        days_data.append({
            "day": d,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "soll": soll,
            "ist": ist,
            "diff": ist - soll,
        })

    month_soll = sum((d["soll"] for d in days_data), Decimal("0"))
    month_ist = sum((d["ist"] for d in days_data), Decimal("0"))
    soll_days_count = sum(1 for d in days_data if d["soll"] > 0)

    prev_month_first = (first_day - timedelta(days=1)).replace(day=1)
    next_month_first = last_day + timedelta(days=1)

    return render(request, "timetracking/month_detail.html", {
        "profile": profile,
        "year": year,
        "month": month,
        "month_name": first_day.strftime("%B %Y"),
        "days_data": days_data,
        "soll_days_count": soll_days_count,
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
        "prev_month": prev_month_first,
        "next_month": next_month_first,
    })
