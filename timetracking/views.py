from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from .forms import UserProfileForm, WorkEntryForm
from .models import WorkEntry
from .utils import (
    calculate_total_saldo,
    calculate_weekly_saldo,
    get_daily_target,
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
                if profile.active_job:
                    return redirect("timetracking:dashboard")
                return redirect("timetracking:job_list")
            return redirect("timetracking:settings_view")
    else:
        form = UserProfileForm(instance=profile)
    return render(request, "timetracking/settings.html", {"form": form, "profile": profile})


@login_required
def dashboard(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    all_jobs = request.user.jobs.all()
    bundesland = profile.bundesland
    today = date.today()

    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]
    entries_this_week = {
        e.date: e
        for e in WorkEntry.objects.filter(
            job=active_job, date__range=[week_days[0], week_days[-1]]
        )
    }

    week_data = []
    for day in week_days:
        entry = entries_this_week.get(day)
        holiday_name = get_holiday_name(day, bundesland)
        is_weekend = day.weekday() >= 5
        soll = get_daily_target(active_job, day, bundesland)
        is_soll = soll > 0

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = soll
        else:
            ist = Decimal("0")

        pending = is_soll and not entry and day >= today
        no_value = (not is_soll and not entry) or (holiday_name and not entry)
        # Werte (Ist/Diff) anzeigen, wenn nicht leer; an Wochenenden/Feiertagen
        # mit Eintrag werden so die geleisteten Stunden sichtbar.
        show_values = not no_value
        week_data.append({
            "day": day,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "is_soll": is_soll,
            "show_values": show_values,
            "soll": soll,
            "ist": ist,
            "diff": Decimal("0") if pending else ist - soll,
            "pending": pending,
            "no_value": no_value,
        })

    week_saldo_data = calculate_weekly_saldo(active_job, bundesland)
    current_week = next((w for w in week_saldo_data if w["is_current"]), None)
    total_saldo = calculate_total_saldo(active_job, bundesland)

    # Monatsübersicht: nur bis heute (keine Zukunfts-Tage zählen)
    first_of_month = today.replace(day=1)
    _, days_in_month = monthrange(today.year, today.month)
    last_of_month = today.replace(day=days_in_month)
    today_entry = WorkEntry.objects.filter(job=active_job, date=today).first()

    month_soll = Decimal("0")
    d = first_of_month
    while d < today:
        month_soll += get_daily_target(active_job, d, bundesland)
        d += timedelta(days=1)
    if today_entry:
        month_soll += get_daily_target(active_job, today, bundesland)

    entries_this_month = WorkEntry.objects.filter(
        job=active_job, date__year=today.year, date__month=today.month, date__lte=today
    )
    month_ist = Decimal("0")
    for e in entries_this_month:
        if e.entry_type == "work":
            month_ist += Decimal(str(e.worked_hours or 0))
        else:
            month_ist += get_daily_target(active_job, e.date, bundesland)

    # Anzeige-Wert: Anzahl Tage im Monat mit Soll > 0 (informativ)
    month_soll_days_total = 0
    d = first_of_month
    while d <= last_of_month:
        if get_daily_target(active_job, d, bundesland) > 0:
            month_soll_days_total += 1
        d += timedelta(days=1)

    prev_month_first = (first_of_month - timedelta(days=1)).replace(day=1)
    next_month_first = last_of_month + timedelta(days=1)

    return render(request, "timetracking/dashboard.html", {
        "profile": profile,
        "active_job": active_job,
        "all_jobs": all_jobs,
        "today": today,
        "week_data": week_data,
        "current_week": current_week,
        "total_saldo": total_saldo,
        "month_soll_days": month_soll_days_total,
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
        "prev_month": prev_month_first,
        "next_month": next_month_first,
    })


@login_required
def entry_create(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    initial = {"job": profile.active_job}
    date_str = request.GET.get("date")
    if date_str:
        try:
            initial["date"] = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    if request.method == "POST":
        form = WorkEntryForm(request.POST, user=request.user, bundesland=profile.bundesland)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Eintrag gespeichert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(initial=initial, user=request.user, bundesland=profile.bundesland)

    return render(request, "timetracking/entry_form.html", {"form": form, "title": "Neuer Eintrag"})


@login_required
def entry_edit(request, pk):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    entry = get_object_or_404(WorkEntry, pk=pk, user=request.user)

    if request.method == "POST":
        form = WorkEntryForm(request.POST, instance=entry, user=request.user, bundesland=profile.bundesland)
        if form.is_valid():
            form.save()
            messages.success(request, "Eintrag aktualisiert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(instance=entry, user=request.user, bundesland=profile.bundesland)

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
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    bundesland = profile.bundesland

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    entries = {
        e.date: e
        for e in WorkEntry.objects.filter(job=active_job, date__range=[first_day, last_day])
    }

    days_data = []
    for i in range(1, days_in_month + 1):
        d = date(year, month, i)
        entry = entries.get(d)
        holiday_name = get_holiday_name(d, bundesland)
        is_weekend = d.weekday() >= 5
        soll = get_daily_target(active_job, d, bundesland)
        is_soll = soll > 0

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = soll
        else:
            ist = Decimal("0")

        days_data.append({
            "day": d,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "is_soll": is_soll,
            "show_values": is_soll or entry is not None,
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
        "active_job": active_job,
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


@login_required
def job_list(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")
    jobs = request.user.jobs.annotate(entry_count=Count("entries")).order_by("name")
    return render(request, "timetracking/job_list.html", {
        "jobs": jobs,
        "profile": profile,
    })


@login_required
def job_create(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")
    from .forms import JobForm
    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.save()
            messages.success(request, f'Job „{job.name}“ wurde erstellt.')
            if profile.active_job is None:
                profile.active_job = job
                profile.save(update_fields=["active_job"])
                return redirect("timetracking:dashboard")
            return redirect("timetracking:job_list")
    else:
        form = JobForm()
    return render(request, "timetracking/job_form.html", {"form": form, "title": "Neuer Job"})


@login_required
def job_edit(request, pk):
    profile = get_or_create_profile(request.user)
    job = get_object_or_404(request.user.jobs, pk=pk)
    from .forms import JobForm
    if request.method == "POST":
        form = JobForm(request.POST, instance=job)
        if form.is_valid():
            form.save()
            messages.success(request, "Job aktualisiert.")
            return redirect("timetracking:job_list")
    else:
        form = JobForm(instance=job)
    return render(request, "timetracking/job_form.html", {"form": form, "title": "Job bearbeiten"})


@login_required
def job_delete(request, pk):
    profile = get_or_create_profile(request.user)
    job = get_object_or_404(request.user.jobs, pk=pk)
    if request.method == "POST":
        if job.entries.exists():
            messages.error(request, f'Job „{job.name}" kann nicht gelöscht werden, da noch Einträge vorhanden sind.')
            return redirect("timetracking:job_list")
        was_active = profile.active_job_id == job.pk
        job.delete()
        if was_active:
            profile.active_job = request.user.jobs.first()
            profile.save()
        messages.success(request, "Job gelöscht.")
        return redirect("timetracking:job_list")
    return render(request, "timetracking/job_confirm_delete.html", {"job": job})


@login_required
def job_activate(request, pk):
    if request.method == "POST":
        job = get_object_or_404(request.user.jobs, pk=pk)
        profile = get_or_create_profile(request.user)
        profile.active_job = job
        profile.save()
    return redirect("timetracking:dashboard")


@login_required
def report_view(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    bundesland = profile.bundesland

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)
    month_name = first_day.strftime("%B %Y")

    entries = {
        e.date: e
        for e in WorkEntry.objects.filter(job=active_job, date__range=[first_day, last_day])
    }

    days_data = []
    for i in range(1, days_in_month + 1):
        d = date(year, month, i)
        entry = entries.get(d)
        holiday_name = get_holiday_name(d, bundesland)
        is_weekend = d.weekday() >= 5
        soll = get_daily_target(active_job, d, bundesland)
        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = soll
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

    all_weeks = calculate_weekly_saldo(active_job, bundesland)
    week_rows = [
        w for w in all_weeks
        if w["week_start"] <= last_day and w["week_end"] >= first_day
    ]
    month_soll = sum((w["soll"] for w in week_rows), Decimal("0"))
    month_ist = sum((w["ist"] for w in week_rows), Decimal("0"))

    return render(request, "timetracking/report.html", {
        "profile": profile,
        "active_job": active_job,
        "year": year,
        "month": month,
        "month_name": month_name,
        "days_data": days_data,
        "week_rows": week_rows,
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
    })


@login_required
def report_pdf(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    bundesland = profile.bundesland

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    entries = {
        e.date: e
        for e in WorkEntry.objects.filter(job=active_job, date__range=[first_day, last_day])
    }
    days_data = []
    for i in range(1, days_in_month + 1):
        d = date(year, month, i)
        entry = entries.get(d)
        holiday_name = get_holiday_name(d, bundesland)
        is_weekend = d.weekday() >= 5
        soll = get_daily_target(active_job, d, bundesland)
        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = soll
        else:
            ist = Decimal("0")
        days_data.append({
            "day": d, "entry": entry, "holiday_name": holiday_name,
            "is_weekend": is_weekend, "soll": soll, "ist": ist, "diff": ist - soll,
        })

    all_weeks = calculate_weekly_saldo(active_job, bundesland)
    week_rows = [w for w in all_weeks if w["week_start"] <= last_day and w["week_end"] >= first_day]
    month_soll = sum((w["soll"] for w in week_rows), Decimal("0"))
    month_ist = sum((w["ist"] for w in week_rows), Decimal("0"))

    from django.template.loader import render_to_string
    html = render_to_string("timetracking/report.html", {
        "profile": profile,
        "active_job": active_job,
        "year": year,
        "month": month,
        "month_name": first_day.strftime("%B %Y"),
        "days_data": days_data,
        "week_rows": week_rows,
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
        "pdf_mode": True,
    }, request=request)

    from weasyprint import HTML
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

    filename = f"arbeitszeitnachweis-{active_job.name.lower().replace(' ', '-')}-{year}-{month:02d}.pdf"
    from django.http import HttpResponse
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def report_email(request, year, month):
    if request.method != "POST":
        return redirect("timetracking:report_view", year=year, month=month)

    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    if not request.user.email:
        messages.error(request, "Keine E-Mail-Adresse im Profil hinterlegt.")
        return redirect("timetracking:report_view", year=year, month=month)

    active_job = profile.active_job
    bundesland = profile.bundesland

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    entries = {
        e.date: e
        for e in WorkEntry.objects.filter(job=active_job, date__range=[first_day, last_day])
    }
    days_data = []
    for i in range(1, days_in_month + 1):
        d = date(year, month, i)
        entry = entries.get(d)
        holiday_name = get_holiday_name(d, bundesland)
        is_weekend = d.weekday() >= 5
        soll = get_daily_target(active_job, d, bundesland)
        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = soll
        else:
            ist = Decimal("0")
        days_data.append({
            "day": d, "entry": entry, "holiday_name": holiday_name,
            "is_weekend": is_weekend, "soll": soll, "ist": ist, "diff": ist - soll,
        })

    all_weeks = calculate_weekly_saldo(active_job, bundesland)
    week_rows = [w for w in all_weeks if w["week_start"] <= last_day and w["week_end"] >= first_day]
    month_soll = sum((w["soll"] for w in week_rows), Decimal("0"))
    month_ist = sum((w["ist"] for w in week_rows), Decimal("0"))

    from django.template.loader import render_to_string
    html = render_to_string("timetracking/report.html", {
        "profile": profile,
        "active_job": active_job,
        "year": year, "month": month,
        "month_name": first_day.strftime("%B %Y"),
        "days_data": days_data,
        "week_rows": week_rows,
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
        "pdf_mode": True,
    }, request=request)

    from weasyprint import HTML
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

    from django.core.mail import EmailMessage
    month_name = first_day.strftime("%B %Y")
    filename = f"arbeitszeitnachweis-{active_job.name.lower().replace(' ', '-')}-{year}-{month:02d}.pdf"
    try:
        email = EmailMessage(
            subject=f"Arbeitszeitnachweis {active_job.name} – {month_name}",
            body=f"Anbei der Arbeitszeitnachweis für {active_job.name}, {month_name}.",
            to=[request.user.email],
        )
        email.attach(filename, pdf, "application/pdf")
        email.send()
        messages.success(request, f"Bericht wurde an {request.user.email} gesendet.")
    except Exception as e:
        messages.error(request, f"E-Mail konnte nicht gesendet werden: {e}")

    return redirect("timetracking:report_view", year=year, month=month)
