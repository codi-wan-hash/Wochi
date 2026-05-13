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


def get_or_create_profile(user):
    from timetracking.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def calculate_total_saldo(user, as_of=None):
    from timetracking.models import WorkEntry
    profile = get_or_create_profile(user)

    if not profile.work_start_date:
        return Decimal("0")

    if as_of is None:
        as_of = date.today()

    if as_of < profile.work_start_date:
        return Decimal("0")

    # Only past days (before as_of) automatically create a soll deficit.
    # For as_of itself, soll is only added if there's already an entry.
    past_end = as_of - timedelta(days=1)
    if past_end >= profile.work_start_date:
        past_soll_days = get_soll_days_in_range(profile.work_start_date, past_end, profile.bundesland)
    else:
        past_soll_days = []

    total_soll = Decimal(str(len(past_soll_days))) * profile.daily_target_hours
    total_ist = Decimal("0")

    entries = WorkEntry.objects.filter(
        user=user,
        date__gte=profile.work_start_date,
        date__lte=as_of,
    )
    for entry in entries:
        if entry.entry_type == "work":
            if entry.worked_hours is not None:
                total_ist += Decimal(str(entry.worked_hours))
        else:
            total_ist += profile.daily_target_hours
        # For the current day (as_of): add soll only when an entry exists
        if entry.date == as_of and is_soll_day(as_of, profile.bundesland):
            total_soll += profile.daily_target_hours

    return total_ist - total_soll
