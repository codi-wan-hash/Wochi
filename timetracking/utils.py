import holidays
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from django.utils import timezone


@lru_cache(maxsize=32)
def _holiday_calendar(bundesland: str):
    """Feiertagskalender je Bundesland, einmal aufgebaut und wiederverwendet.

    Ohne Cache wurde er pro abgefragtem Tag neu instanziiert — bei einem
    Jahresbericht rund 730-mal. Der Kalender füllt Jahre bei Bedarf selbst nach.
    """
    return holidays.country_holidays("DE", subdiv=bundesland)


def is_holiday(d: date, bundesland: str) -> bool:
    return d in _holiday_calendar(bundesland)


def get_holiday_name(d: date, bundesland: str) -> str:
    return _holiday_calendar(bundesland).get(d, "")


def is_soll_day(d: date, bundesland: str) -> bool:
    return d.weekday() < 5 and not is_holiday(d, bundesland)


def get_soll_days_in_range(start: date, end: date, bundesland: str) -> list:
    days = []
    current = start
    while current <= end:
        if is_soll_day(current, bundesland):
            days.append(current)
        current += timedelta(days=1)
    return days


def get_daily_target(job, d: date, bundesland: str) -> Decimal:
    """
    Per-day Soll for a job.

    Pre-work_start_date: 0 (job didn't apply yet).
    Non-holiday: configured hours for that weekday.
    Holiday: depends on job.holiday_credit_basis —
      - "per_day": 0 (full relief equals configured hours).
      - "weekly_average": config − weekly_avg (relief always equals the weekly
        average regardless of which weekday the holiday falls on).
    """
    if job.work_start_date and d < job.work_start_date:
        return Decimal("0")
    config = job.hours_for_weekday(d.weekday())
    if not is_holiday(d, bundesland):
        return config
    if job.holiday_credit_basis == "weekly_average" and config > 0:
        return config - job.weekly_average_hours
    return Decimal("0")


def has_target(job, d: date, bundesland: str) -> bool:
    return get_daily_target(job, d, bundesland) > 0


def get_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def get_or_create_profile(user):
    from timetracking.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def calculate_weekly_saldo(job, bundesland: str, as_of: date = None) -> list:
    """
    Returns list of weekly saldo dicts from job.work_start_date through as_of.
    Each dict: week_start, week_end, iso_week, year, soll, ist, saldo, is_current.
    Soll = sum of per-weekday target hours (holidays zero out the day).
    """
    if not job.work_start_date:
        return []

    if as_of is None:
        as_of = timezone.localdate()

    if as_of < job.work_start_date:
        return []

    from timetracking.models import WorkEntry

    # Eine Query für den gesamten Zeitraum statt einer pro Woche. Bei einem
    # zwei Jahre alten Job waren das vorher ~100 Queries pro Aufruf.
    entries_by_date = {
        e.date: e
        for e in WorkEntry.objects.filter(
            job=job, date__range=[job.work_start_date, as_of]
        )
    }

    current_week_start = get_week_start(as_of)
    weeks = []
    week_start = get_week_start(job.work_start_date)

    while week_start <= current_week_start:
        week_end = week_start + timedelta(days=6)
        effective_start = max(week_start, job.work_start_date)
        effective_end = min(week_end, as_of)

        week_soll = Decimal("0")
        week_ist = Decimal("0")
        has_entries = False
        d = effective_start
        while d <= effective_end:
            week_soll += get_daily_target(job, d, bundesland)
            entry = entries_by_date.get(d)
            if entry is not None:
                has_entries = True
                if entry.entry_type == "work":
                    if entry.worked_hours is not None:
                        week_ist += Decimal(str(entry.worked_hours))
                else:
                    week_ist += get_daily_target(job, d, bundesland)
            d += timedelta(days=1)

        is_current = week_start == current_week_start

        if is_current and not has_entries:
            week_soll = Decimal("0")

        weeks.append({
            "week_start": week_start,
            "week_end": week_end,
            "iso_week": week_start.isocalendar()[1],
            "year": week_start.year,
            "soll": week_soll,
            "ist": week_ist,
            "saldo": week_ist - week_soll,
            "is_current": is_current,
        })

        week_start += timedelta(weeks=1)

    return weeks


def calculate_total_saldo(job, bundesland: str, as_of: date = None) -> Decimal:
    weeks = calculate_weekly_saldo(job, bundesland, as_of)
    return sum((w["saldo"] for w in weeks), Decimal("0"))
