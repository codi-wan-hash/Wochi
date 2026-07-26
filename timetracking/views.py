import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils.dates import MONTHS
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import ReportRangeForm, UserProfileForm, WorkEntryForm
from .models import WorkEntry
from .periods import (
    MAX_RANGE_DAYS,
    add_months,
    build_day_rows,
    build_week_rows,
    month_bounds,
    parse_date_param,
    saldo_until,
    summarize_rows,
    today_local,
    week_bounds,
)
from .utils import calculate_total_saldo, get_or_create_profile, get_week_start

logger = logging.getLogger(__name__)


def _safe_next(request, fallback="timetracking:dashboard"):
    """Ziel aus ?next= — nur wenn es auf denselben Host zeigt.

    Ohne diese Prüfung wäre der Parameter ein offener Redirect.
    """
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return resolve_url(fallback)


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
    today = today_local()

    # Ein Stichtag steuert Wochen- und Monatskarte gemeinsam.
    focus = parse_date_param(request.GET.get("datum"), today)

    week_start, week_end = week_bounds(focus)
    week_data = build_day_rows(active_job, bundesland, week_start, week_end, today)
    week_totals = summarize_rows(week_data)

    prev_week_day = focus - timedelta(days=7)
    next_week_day = focus + timedelta(days=7)
    # Zurückblättern endet am Beginn des Jobs — davor gibt es nichts zu sehen.
    prev_week_available = week_bounds(prev_week_day)[1] >= active_job.work_start_date

    month_start, month_end = month_bounds(focus.year, focus.month)
    month_rows = build_day_rows(active_job, bundesland, month_start, month_end, today)
    month_totals = summarize_rows(month_rows)

    total_saldo = calculate_total_saldo(active_job, bundesland)

    return render(request, "timetracking/dashboard.html", {
        "profile": profile,
        "active_job": active_job,
        "all_jobs": all_jobs,
        "today": today,
        "focus_date": focus,
        "week_data": week_data,
        "week_start": week_start,
        "week_end": week_end,
        "week_iso": week_start.isocalendar()[1],
        "week_totals": week_totals,
        "prev_week_day": prev_week_day,
        "next_week_day": next_week_day,
        "prev_week_available": prev_week_available,
        "is_current_week": week_start == get_week_start(today),
        "total_saldo": total_saldo,
        "month_start": month_start,
        "month_end": month_end,
        "month_soll_days": month_totals["soll_days"],
        "month_soll": month_totals["soll"],
        "month_ist": month_totals["ist"],
        "month_saldo": month_totals["saldo"],
        "prev_month": add_months(focus, -1),
        "next_month": add_months(focus, 1),
    })


@login_required
def entry_create(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    initial = {"job": profile.active_job}
    entry_date = parse_date_param(request.GET.get("date"))
    if entry_date:
        initial["date"] = entry_date

    if request.method == "POST":
        form = WorkEntryForm(request.POST, user=request.user, bundesland=profile.bundesland)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Eintrag gespeichert.")
            return redirect(_safe_next(request))
    else:
        form = WorkEntryForm(initial=initial, user=request.user, bundesland=profile.bundesland)

    return render(request, "timetracking/entry_form.html", {
        "form": form,
        "title": "Neuer Eintrag",
        "next": _safe_next(request),
    })


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
            return redirect(_safe_next(request))
    else:
        form = WorkEntryForm(instance=entry, user=request.user, bundesland=profile.bundesland)

    return render(request, "timetracking/entry_form.html", {
        "form": form,
        "title": "Eintrag bearbeiten",
        "next": _safe_next(request),
    })


@login_required
def entry_delete(request, pk):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    entry = get_object_or_404(WorkEntry, pk=pk, user=request.user)

    if request.method == "POST":
        entry.delete()
        messages.success(request, "Eintrag gelöscht.")
        return redirect(_safe_next(request))

    return render(request, "timetracking/entry_confirm_delete.html", {
        "entry": entry,
        "next": _safe_next(request),
    })


@login_required
def month_detail(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    # Monats-/Jahresauswahl: auf die kanonische URL umleiten, damit die Seite
    # bookmarkbar bleibt und kein JavaScript nötig ist.
    jump_year = request.GET.get("year")
    jump_month = request.GET.get("month")
    if jump_year and jump_month:
        try:
            return redirect(
                "timetracking:month_detail", year=int(jump_year), month=int(jump_month)
            )
        except (TypeError, ValueError):
            pass

    active_job = profile.active_job
    bundesland = profile.bundesland
    today = today_local()

    first_day, last_day = month_bounds(year, month)
    days_data = build_day_rows(active_job, bundesland, first_day, last_day, today)
    totals = summarize_rows(days_data)

    prev_month_first = add_months(first_day, -1)
    next_month_first = add_months(first_day, 1)

    return render(request, "timetracking/month_detail.html", {
        "profile": profile,
        "active_job": active_job,
        "year": year,
        "month": month,
        "first_day": first_day,
        "last_day": last_day,
        "days_data": days_data,
        "soll_days_count": totals["soll_days"],
        "month_soll": totals["soll"],
        "month_ist": totals["ist"],
        "month_saldo": totals["saldo"],
        "prev_month": prev_month_first,
        "next_month": next_month_first,
        "today": today,
        "is_current_month": (today.year, today.month) == (year, month),
        # MONTHS ist übersetzt; strftime("%B") würde die System-Locale nehmen
        # und in der deutschen App englische Monatsnamen liefern.
        "month_choices": sorted(MONTHS.items()),
        "year_choices": range(active_job.work_start_date.year, today.year + 2),
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


# --- Bericht ---------------------------------------------------------------

def _report_presets(today):
    """Schnellauswahl für die Berichtsleiste."""
    this_month = month_bounds(today.year, today.month)
    prev_first = add_months(today, -1)
    last_month = month_bounds(prev_first.year, prev_first.month)
    return [
        {"label": "Dieser Monat", "von": this_month[0], "bis": this_month[1]},
        {"label": "Letzter Monat", "von": last_month[0], "bis": last_month[1]},
        {"label": "Dieses Jahr", "von": date(today.year, 1, 1), "bis": date(today.year, 12, 31)},
        {"label": "Letzte 30 Tage", "von": today - timedelta(days=29), "bis": today},
    ]


def _resolve_range(request, today):
    """(von, bis, form) aus den GET-Parametern. Ohne Parameter: aktueller Monat.

    Gibt (None, None, form) zurück, wenn die Eingabe ungültig ist.
    """
    if request.GET.get("von") or request.GET.get("bis"):
        form = ReportRangeForm(request.GET)
        if form.is_valid():
            return form.cleaned_data["von"], form.cleaned_data["bis"], form
        return None, None, form

    start, end = month_bounds(today.year, today.month)
    return start, end, ReportRangeForm(initial={"von": start, "bis": end})


def _report_context(profile, start, end, today):
    """Alle Zahlen des Berichts aus einer einzigen Quelle.

    Tageszeilen, Wochenzeilen und Gesamtsumme stammen aus denselben Rohdaten,
    damit die Summen zueinander passen.
    """
    active_job = profile.active_job
    bundesland = profile.bundesland

    days_data = build_day_rows(active_job, bundesland, start, end, today)
    totals = summarize_rows(days_data)
    week_rows = build_week_rows(days_data)
    saldo_before = saldo_until(active_job, bundesland, start - timedelta(days=1), today)

    return {
        "profile": profile,
        "active_job": active_job,
        "start": start,
        "end": end,
        "days_data": days_data,
        "week_rows": week_rows,
        "range_soll": totals["soll"],
        "range_ist": totals["ist"],
        "range_saldo": totals["saldo"],
        "saldo_before": saldo_before,
        "saldo_after": saldo_before + totals["saldo"],
    }


def _report_filename(active_job, start, end):
    slug = active_job.name.lower().replace(" ", "-")
    return f"arbeitszeitnachweis-{slug}-{start:%Y-%m-%d}_bis_{end:%Y-%m-%d}.pdf"


def _render_report_pdf(request, context):
    from django.template.loader import render_to_string
    from weasyprint import HTML

    html = render_to_string(
        "timetracking/report.html", {**context, "pdf_mode": True}, request=request
    )
    return HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()


@login_required
def report_view(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    today = today_local()
    start, end, form = _resolve_range(request, today)

    context = {
        "profile": profile,
        "active_job": profile.active_job,
        "form": form,
        "presets": _report_presets(today),
        "max_range_days": MAX_RANGE_DAYS,
    }
    if start is not None:
        context.update(_report_context(profile, start, end, today))

    return render(request, "timetracking/report.html", context)


@login_required
def report_pdf(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    today = today_local()
    start, end, _form = _resolve_range(request, today)
    if start is None:
        messages.error(request, "Ungültiger Zeitraum.")
        return redirect("timetracking:report_view")

    context = _report_context(profile, start, end, today)
    pdf = _render_report_pdf(request, context)

    from django.http import HttpResponse
    response = HttpResponse(pdf, content_type="application/pdf")
    filename = _report_filename(profile.active_job, start, end)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def report_email(request):
    if request.method != "POST":
        return redirect("timetracking:report_view")

    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    today = today_local()
    start, end, _form = _resolve_range(request, today)
    if start is None:
        messages.error(request, "Ungültiger Zeitraum.")
        return redirect("timetracking:report_view")

    range_query = f"?von={start:%Y-%m-%d}&bis={end:%Y-%m-%d}"

    if not request.user.email:
        messages.error(request, "Keine E-Mail-Adresse im Profil hinterlegt.")
        return redirect(resolve_url("timetracking:report_view") + range_query)

    context = _report_context(profile, start, end, today)
    pdf = _render_report_pdf(request, context)

    from django.core.mail import EmailMessage
    active_job = profile.active_job
    range_label = f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"
    try:
        email = EmailMessage(
            subject=f"Arbeitszeitnachweis {active_job.name} – {range_label}",
            body=f"Anbei der Arbeitszeitnachweis für {active_job.name}, {range_label}.",
            to=[request.user.email],
        )
        email.attach(_report_filename(active_job, start, end), pdf, "application/pdf")
        email.send()
        messages.success(request, f"Bericht wurde an {request.user.email} gesendet.")
    except Exception:
        # Die rohe Fehlermeldung (SMTP-Host, Zugangsdaten) gehört nicht ins UI.
        logger.exception("Versand des Arbeitszeitnachweises fehlgeschlagen")
        messages.error(
            request,
            "Der Bericht konnte nicht versendet werden. Bitte später erneut versuchen.",
        )

    return redirect(resolve_url("timetracking:report_view") + range_query)


@login_required
def report_month_redirect(request, year, month):
    """Alte Monats-URL auf den Zeitraum-Bericht umleiten (Bookmarks)."""
    start, end = month_bounds(year, month)
    return redirect(
        f"{resolve_url('timetracking:report_view')}?von={start:%Y-%m-%d}&bis={end:%Y-%m-%d}"
    )
