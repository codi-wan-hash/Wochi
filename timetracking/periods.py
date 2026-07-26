"""Zeitraum-Logik für die Arbeitszeiterfassung.

Ein Tag wird genau hier zu einer Zeile mit Soll/Ist/Diff. Dashboard,
Monatsdetail und Bericht benutzen dieselben Funktionen, damit sie für
denselben Zeitraum nicht unterschiedliche Zahlen anzeigen.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.http import Http404
from django.utils import timezone

from .utils import get_daily_target, get_holiday_name, get_week_start

MIN_YEAR = 2000
MAX_YEAR = 2100

# Obergrenze für einen Berichtszeitraum. Schützt davor, dass ?von=1900-01-01
# hunderttausende Tageszeilen erzeugt.
MAX_RANGE_DAYS = 366


def today_local() -> date:
    """Heutiges Datum in der konfigurierten Zeitzone (Europe/Berlin)."""
    return timezone.localdate()


def parse_date_param(raw, default=None):
    """Ein Datum aus einem GET-Parameter lesen; bei Unsinn den Default."""
    try:
        return date.fromisoformat(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return default


def week_bounds(d: date):
    monday = get_week_start(d)
    return monday, monday + timedelta(days=6)


def month_bounds(year: int, month: int):
    """Erster und letzter Tag des Monats. Http404 bei ungültigen Werten."""
    if not (MIN_YEAR <= year <= MAX_YEAR) or not (1 <= month <= 12):
        raise Http404("Ungültiger Monat.")
    _, days_in_month = monthrange(year, month)
    return date(year, month, 1), date(year, month, days_in_month)


def add_months(d: date, delta: int) -> date:
    """Um `delta` Monate verschieben und auf den Monatsersten setzen."""
    index = d.year * 12 + (d.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def clamp_year(year: int) -> int:
    return max(MIN_YEAR, min(MAX_YEAR, year))


def build_day_rows(job, bundesland: str, start: date, end: date, today: date = None) -> list:
    """Eine Zeile pro Tag im Zeitraum [start, end].

    Zukünftige Tage ohne Eintrag gelten als `pending`: sie zählen nicht ins
    Soll und erzeugen keine Differenz. Sonst würde ein laufender Monat immer
    ein Minus für die noch nicht gearbeiteten Tage ausweisen.
    """
    from .models import WorkEntry

    if today is None:
        today = today_local()
    if end < start:
        return []

    entries = {
        e.date: e
        for e in WorkEntry.objects.filter(job=job, date__range=[start, end])
    }

    rows = []
    d = start
    while d <= end:
        entry = entries.get(d)
        holiday_name = get_holiday_name(d, bundesland)
        soll = get_daily_target(job, d, bundesland)
        is_soll = soll > 0

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = soll
        else:
            ist = Decimal("0")

        pending = is_soll and entry is None and d >= today
        # Wochenenden und Feiertage ohne Eintrag haben keinen Wert zu zeigen.
        no_value = entry is None and (not is_soll or bool(holiday_name))

        rows.append({
            "day": d,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": d.weekday() >= 5,
            "is_soll": is_soll,
            "show_values": not no_value,
            "soll": soll,
            "soll_counted": Decimal("0") if pending else soll,
            "ist": ist,
            "diff": Decimal("0") if pending else ist - soll,
            "pending": pending,
            "no_value": no_value,
        })
        d += timedelta(days=1)

    return rows


def summarize_rows(rows) -> dict:
    """Summen über Tageszeilen. Soll zählt `soll_counted` (ohne pending-Tage)."""
    soll = sum((r["soll_counted"] for r in rows), Decimal("0"))
    ist = sum((r["ist"] for r in rows), Decimal("0"))
    return {
        "soll": soll,
        "ist": ist,
        "saldo": ist - soll,
        "soll_days": sum(1 for r in rows if r["soll"] > 0),
    }


def saldo_until(job, bundesland: str, until: date, today: date = None):
    """Saldo vom Jobstart bis einschließlich `until`.

    Bewusst über build_day_rows statt über calculate_weekly_saldo: nur so gilt
    im Bericht „Saldo davor + Saldo im Zeitraum = Saldo danach" exakt.
    """
    if today is None:
        today = today_local()
    if not job.work_start_date or until < job.work_start_date:
        return Decimal("0")
    rows = build_day_rows(job, bundesland, job.work_start_date, until, today)
    return summarize_rows(rows)["saldo"]


def build_week_rows(day_rows) -> list:
    """Tageszeilen nach ISO-Woche gruppieren.

    Die Wochen sind auf den Zeitraum beschnitten: eine Woche, die über den
    Monatsrand ragt, erscheint nur mit ihrem Anteil. Nur so ergibt die Summe
    der Wochenzeilen dieselbe Zahl wie die Summe der Tageszeilen.
    """
    buckets = []
    current = None
    for row in day_rows:
        key = row["day"].isocalendar()[:2]
        if current is None or current["key"] != key:
            current = {"key": key, "rows": []}
            buckets.append(current)
        current["rows"].append(row)

    weeks = []
    for bucket in buckets:
        rows = bucket["rows"]
        totals = summarize_rows(rows)
        iso_year, iso_week = bucket["key"]
        weeks.append({
            "iso_week": iso_week,
            "year": iso_year,
            "week_start": rows[0]["day"],
            "week_end": rows[-1]["day"],
            "soll": totals["soll"],
            "ist": totals["ist"],
            "saldo": totals["saldo"],
        })
    return weeks
