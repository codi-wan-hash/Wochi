import holidays
from datetime import date, timedelta
from decimal import Decimal


def is_holiday(d: date, bundesland: str) -> bool:
    de = holidays.country_holidays("DE", subdiv=bundesland)
    return d in de


def get_holiday_name(d: date, bundesland: str) -> str:
    de = holidays.country_holidays("DE", subdiv=bundesland)
    return de.get(d, "")


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
    """
    if not job.work_start_date:
        return []

    if as_of is None:
        as_of = date.today()

    if as_of < job.work_start_date:
        return []

    from timetracking.models import WorkEntry

    current_week_start = get_week_start(as_of)
    weeks = []
    week_start = get_week_start(job.work_start_date)

    while week_start <= get_week_start(as_of):
        week_end = week_start + timedelta(days=6)
        effective_start = max(week_start, job.work_start_date)
        effective_end = min(week_end, as_of)

        # Soll = effektive Werktage × Tagesäquivalent (Wochensoll / 5).
        # Feiertage/Wochenenden reduzieren das Soll, ohne dass die übrigen
        # Tage "aufgepumpt" werden.
        daily_equiv = job.weekly_target_hours / Decimal("5")
        eff_soll = len(get_soll_days_in_range(effective_start, effective_end, bundesland))
        week_soll = daily_equiv * Decimal(eff_soll)

        entries = WorkEntry.objects.filter(job=job, date__range=[effective_start, effective_end])

        week_ist = Decimal("0")
        for entry in entries:
            if entry.entry_type == "work":
                if entry.worked_hours is not None:
                    week_ist += Decimal(str(entry.worked_hours))
            else:
                week_ist += daily_equiv

        is_current = week_start == current_week_start

        # Current week without entries: no deficit yet
        if is_current and not entries.exists():
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
