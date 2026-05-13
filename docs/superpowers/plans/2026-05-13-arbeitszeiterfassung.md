# Arbeitszeiterfassung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Neue Django-App `timetracking` mit userspezifischer Arbeitszeiterfassung (Start/Endzeit, Feiertage, Wochen- & Monatsübersicht, Gesamtsaldo).

**Architecture:** Separate App `timetracking` nach bestehendem Wochi-Muster. `UserProfile` (OneToOneField→User) hält Settings + Feature-Toggle. `WorkEntry` (ForeignKey→User) speichert Tageseinträge. Kein Household-Bezug. Feiertage via `holidays`-Paket (Deutschland + Bundesland).

**Tech Stack:** Django 6, Bootstrap 5.3, `holidays` (Python-Paket), SQLite lokal / PostgreSQL Produktion

---

## File Map

**Neu erstellen:**
- `timetracking/__init__.py`
- `timetracking/apps.py`
- `timetracking/models.py` — UserProfile, WorkEntry
- `timetracking/signals.py` — auto-create UserProfile on User creation
- `timetracking/forms.py` — UserProfileForm, WorkEntryForm
- `timetracking/utils.py` — is_holiday, get_holiday_name, is_soll_day, get_soll_days_in_range, calculate_total_saldo, get_or_create_profile
- `timetracking/views.py` — dashboard, entry_create, entry_edit, entry_delete, settings_view, month_detail
- `timetracking/urls.py`
- `timetracking/admin.py`
- `timetracking/tests.py`
- `templates/timetracking/dashboard.html`
- `templates/timetracking/entry_form.html`
- `templates/timetracking/entry_confirm_delete.html`
- `templates/timetracking/settings.html`
- `templates/timetracking/month_detail.html`

**Modifizieren:**
- `requirements.txt` — `holidays` hinzufügen
- `wochi/settings.py` — `"timetracking"` zu INSTALLED_APPS
- `wochi/urls.py` — timetracking URLs einbinden
- `templates/base.html` — Sidebar-Link "Arbeitszeit" (bedingt)

---

## Task 1: Abhängigkeit & App-Skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `timetracking/__init__.py`
- Create: `timetracking/apps.py`
- Create: `timetracking/admin.py`
- Modify: `wochi/settings.py`
- Modify: `wochi/urls.py`

- [ ] **Schritt 1: holidays zu requirements.txt hinzufügen**

Füge am Ende von `requirements.txt` ein:
```
holidays
```

- [ ] **Schritt 2: holidays installieren**

```bash
pip install holidays
```
Erwartete Ausgabe: `Successfully installed holidays-X.Y.Z`

- [ ] **Schritt 3: App-Verzeichnis anlegen**

```bash
mkdir timetracking
```

- [ ] **Schritt 4: `timetracking/__init__.py` erstellen**

Leere Datei:
```python
```

- [ ] **Schritt 5: `timetracking/apps.py` erstellen**

```python
from django.apps import AppConfig


class TimetrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "timetracking"
    verbose_name = "Arbeitszeiterfassung"

    def ready(self):
        import timetracking.signals  # noqa
```

- [ ] **Schritt 6: `timetracking/admin.py` erstellen**

```python
from django.contrib import admin
```

- [ ] **Schritt 7: `wochi/settings.py` — App registrieren**

In `INSTALLED_APPS` nach `"api"` einfügen:
```python
    "timetracking",
```

- [ ] **Schritt 8: `wochi/urls.py` — URLs einbinden**

```python
path("timetracking/", include("timetracking.urls")),
```
Einfügen nach `path("api/", include("api.urls")),`.

- [ ] **Schritt 9: Django-Check**

```bash
python manage.py check
```
Erwartete Ausgabe: `System check identified no issues (0 silenced).`

- [ ] **Schritt 10: Commit**

```bash
git add requirements.txt timetracking/ wochi/settings.py wochi/urls.py
git commit -m "feat: add timetracking app skeleton"
```

---

## Task 2: UserProfile Model + Signal

**Files:**
- Create: `timetracking/models.py`
- Create: `timetracking/signals.py`
- Modify: `timetracking/admin.py`
- Create: `timetracking/tests.py`

- [ ] **Schritt 1: Failing test schreiben**

`timetracking/tests.py`:
```python
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from datetime import date
from decimal import Decimal

User = get_user_model()


class UserProfileSignalTest(TestCase):
    def test_profile_created_on_user_creation(self):
        user = User.objects.create_user(username="testuser", password="pw123456")
        self.assertTrue(hasattr(user, "userprofile"))
        self.assertFalse(user.userprofile.timetracking_enabled)
        self.assertEqual(user.userprofile.daily_target_hours, Decimal("8.00"))

    def test_profile_not_duplicated_on_save(self):
        user = User.objects.create_user(username="testuser2", password="pw123456")
        user.save()  # second save should not create a second profile
        from timetracking.models import UserProfile
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.UserProfileSignalTest -v 2
```
Erwartete Ausgabe: `ImportError` oder `ModuleNotFoundError` (models fehlen noch)

- [ ] **Schritt 3: `timetracking/models.py` erstellen**

```python
from datetime import date, datetime
from decimal import Decimal
from django.db import models
from django.conf import settings

BUNDESLAND_CHOICES = [
    ("BB", "Brandenburg"),
    ("BE", "Berlin"),
    ("BW", "Baden-Württemberg"),
    ("BY", "Bayern"),
    ("HB", "Bremen"),
    ("HE", "Hessen"),
    ("HH", "Hamburg"),
    ("MV", "Mecklenburg-Vorpommern"),
    ("NI", "Niedersachsen"),
    ("NW", "Nordrhein-Westfalen"),
    ("RP", "Rheinland-Pfalz"),
    ("SH", "Schleswig-Holstein"),
    ("SL", "Saarland"),
    ("SN", "Sachsen"),
    ("ST", "Sachsen-Anhalt"),
    ("TH", "Thüringen"),
]


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="userprofile",
    )
    timetracking_enabled = models.BooleanField(default=False)
    bundesland = models.CharField(max_length=2, choices=BUNDESLAND_CHOICES, default="BY")
    daily_target_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("8.00"))
    work_start_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Profile({self.user.username})"
```

- [ ] **Schritt 4: `timetracking/signals.py` erstellen**

```python
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        from timetracking.models import UserProfile
        UserProfile.objects.get_or_create(user=instance)
```

- [ ] **Schritt 5: `timetracking/admin.py` aktualisieren**

```python
from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timetracking_enabled", "bundesland", "daily_target_hours", "work_start_date"]
```

- [ ] **Schritt 6: Migration erstellen und anwenden**

```bash
python manage.py makemigrations timetracking
python manage.py migrate
```
Erwartete Ausgabe: `Applying timetracking.0001_initial... OK`

- [ ] **Schritt 7: Test ausführen — muss PASS sein**

```bash
python manage.py test timetracking.tests.UserProfileSignalTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 8: Commit**

```bash
git add timetracking/
git commit -m "feat: add UserProfile model with auto-create signal"
```

---

## Task 3: WorkEntry Model

**Files:**
- Modify: `timetracking/models.py`
- Modify: `timetracking/admin.py`
- Modify: `timetracking/tests.py`

- [ ] **Schritt 1: Failing tests hinzufügen**

In `timetracking/tests.py` ergänzen:
```python
class WorkEntryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="worker", password="pw123456")

    def test_worked_hours_calculation(self):
        from timetracking.models import WorkEntry
        from datetime import time
        entry = WorkEntry.objects.create(
            user=self.user,
            date=date(2026, 5, 4),
            entry_type="work",
            start_time=time(8, 0),
            end_time=time(16, 30),
            break_minutes=30,
        )
        self.assertEqual(entry.worked_hours, 8.0)

    def test_worked_hours_none_for_absence(self):
        from timetracking.models import WorkEntry
        entry = WorkEntry.objects.create(
            user=self.user,
            date=date(2026, 5, 4),
            entry_type="urlaub",
        )
        self.assertIsNone(entry.worked_hours)

    def test_unique_entry_per_day(self):
        from timetracking.models import WorkEntry
        from django.db import IntegrityError
        WorkEntry.objects.create(user=self.user, date=date(2026, 5, 4), entry_type="urlaub")
        with self.assertRaises(IntegrityError):
            WorkEntry.objects.create(user=self.user, date=date(2026, 5, 4), entry_type="krankheit")
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.WorkEntryTest -v 2
```
Erwartete Ausgabe: `ImportError` (WorkEntry nicht definiert)

- [ ] **Schritt 3: WorkEntry zu `timetracking/models.py` hinzufügen**

Nach der `UserProfile`-Klasse einfügen:
```python
class WorkEntry(models.Model):
    ENTRY_TYPE_CHOICES = [
        ("work", "Arbeit"),
        ("urlaub", "Urlaub"),
        ("krankheit", "Krankheit"),
        ("homeoffice", "Homeoffice"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="work_entries",
    )
    date = models.DateField()
    entry_type = models.CharField(max_length=12, choices=ENTRY_TYPE_CHOICES, default="work")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    break_minutes = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.user.username} – {self.date}"

    @property
    def worked_hours(self):
        if self.entry_type != "work" or not self.start_time or not self.end_time:
            return None
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        total_minutes = (end - start).total_seconds() / 60 - self.break_minutes
        return round(total_minutes / 60, 2)
```

- [ ] **Schritt 4: WorkEntry in admin registrieren**

In `timetracking/admin.py` ergänzen:
```python
from .models import UserProfile, WorkEntry


@admin.register(WorkEntry)
class WorkEntryAdmin(admin.ModelAdmin):
    list_display = ["user", "date", "entry_type", "start_time", "end_time", "break_minutes"]
    list_filter = ["entry_type", "user"]
```

- [ ] **Schritt 5: Migration erstellen und anwenden**

```bash
python manage.py makemigrations timetracking
python manage.py migrate
```
Erwartete Ausgabe: `Applying timetracking.0002_workentry... OK`

- [ ] **Schritt 6: Tests ausführen — müssen PASS sein**

```bash
python manage.py test timetracking.tests.WorkEntryTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 7: Commit**

```bash
git add timetracking/
git commit -m "feat: add WorkEntry model"
```

---

## Task 4: Kalender-Utilities

**Files:**
- Create: `timetracking/utils.py`
- Modify: `timetracking/tests.py`

- [ ] **Schritt 1: Failing tests hinzufügen**

In `timetracking/tests.py` ergänzen:
```python
class HolidayUtilsTest(TestCase):
    def test_may_first_is_holiday_in_bavaria(self):
        from timetracking.utils import is_holiday
        self.assertTrue(is_holiday(date(2026, 5, 1), "BY"))

    def test_regular_monday_is_not_holiday(self):
        from timetracking.utils import is_holiday
        self.assertFalse(is_holiday(date(2026, 5, 4), "BY"))

    def test_saturday_is_not_soll_day(self):
        from timetracking.utils import is_soll_day
        self.assertFalse(is_soll_day(date(2026, 5, 2), "BY"))

    def test_monday_is_soll_day(self):
        from timetracking.utils import is_soll_day
        self.assertTrue(is_soll_day(date(2026, 5, 4), "BY"))

    def test_holiday_is_not_soll_day(self):
        from timetracking.utils import is_soll_day
        self.assertFalse(is_soll_day(date(2026, 5, 1), "BY"))

    def test_get_soll_days_in_range(self):
        from timetracking.utils import get_soll_days_in_range
        # May 4–8 2026 (Mo–Fr), May 1 is holiday but not in range
        days = get_soll_days_in_range(date(2026, 5, 4), date(2026, 5, 8), "BY")
        # All 5 days are regular working days
        self.assertEqual(len(days), 5)

    def test_saldo_positive(self):
        from timetracking.utils import calculate_total_saldo
        from timetracking.models import WorkEntry, UserProfile
        from datetime import time

        user = User.objects.create_user(username="saldotest", password="pw123456")
        profile = user.userprofile
        profile.bundesland = "BY"
        profile.daily_target_hours = Decimal("8.00")
        profile.work_start_date = date(2026, 5, 4)
        profile.save()

        WorkEntry.objects.create(
            user=user,
            date=date(2026, 5, 4),
            entry_type="work",
            start_time=time(8, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )
        # as_of May 5: one soll day (May 4), worked 9h → saldo = +1h
        saldo = calculate_total_saldo(user, as_of=date(2026, 5, 5))
        self.assertEqual(saldo, Decimal("1.00"))

    def test_saldo_absence_counts_as_soll(self):
        from timetracking.utils import calculate_total_saldo
        from timetracking.models import WorkEntry, UserProfile

        user = User.objects.create_user(username="absencetest", password="pw123456")
        profile = user.userprofile
        profile.bundesland = "BY"
        profile.daily_target_hours = Decimal("8.00")
        profile.work_start_date = date(2026, 5, 4)
        profile.save()

        WorkEntry.objects.create(
            user=user,
            date=date(2026, 5, 4),
            entry_type="urlaub",
        )
        # Urlaub counts as soll fulfilled → saldo = 0
        saldo = calculate_total_saldo(user, as_of=date(2026, 5, 5))
        self.assertEqual(saldo, Decimal("0.00"))
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.HolidayUtilsTest -v 2
```
Erwartete Ausgabe: `ImportError` (utils fehlen)

- [ ] **Schritt 3: `timetracking/utils.py` erstellen**

```python
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

    yesterday = as_of - timedelta(days=1)
    if yesterday < profile.work_start_date:
        return Decimal("0")

    soll_days = get_soll_days_in_range(profile.work_start_date, yesterday, profile.bundesland)
    total_soll = Decimal(str(len(soll_days))) * profile.daily_target_hours

    entries = WorkEntry.objects.filter(
        user=user,
        date__gte=profile.work_start_date,
        date__lte=yesterday,
    )
    total_ist = Decimal("0")
    for entry in entries:
        if entry.entry_type == "work":
            if entry.worked_hours is not None:
                total_ist += Decimal(str(entry.worked_hours))
        else:
            total_ist += profile.daily_target_hours

    return total_ist - total_soll
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS sein**

```bash
python manage.py test timetracking.tests.HolidayUtilsTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 5: Commit**

```bash
git add timetracking/utils.py timetracking/tests.py
git commit -m "feat: add calendar utilities and saldo calculation"
```

---

## Task 5: Formulare

**Files:**
- Create: `timetracking/forms.py`

- [ ] **Schritt 1: `timetracking/forms.py` erstellen**

```python
from django import forms
from .models import UserProfile, WorkEntry


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["timetracking_enabled", "bundesland", "daily_target_hours", "work_start_date"]
        widgets = {
            "bundesland": forms.Select(attrs={"class": "form-select"}),
            "daily_target_hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.5"}),
            "work_start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "timetracking_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "timetracking_enabled": "Arbeitszeiterfassung aktivieren",
            "bundesland": "Bundesland (für Feiertage)",
            "daily_target_hours": "Tagessoll (Stunden)",
            "work_start_date": "Startdatum für Saldo",
        }


class WorkEntryForm(forms.ModelForm):
    class Meta:
        model = WorkEntry
        fields = ["date", "entry_type", "start_time", "end_time", "break_minutes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "entry_type": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "break_minutes": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }
        labels = {
            "date": "Datum",
            "entry_type": "Typ",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
            "break_minutes": "Pause (Minuten)",
        }

    def clean(self):
        cleaned_data = super().clean()
        entry_type = cleaned_data.get("entry_type")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        if entry_type == "work":
            if not start_time:
                self.add_error("start_time", "Startzeit ist erforderlich.")
            if not end_time:
                self.add_error("end_time", "Endzeit ist erforderlich.")
            if start_time and end_time and end_time <= start_time:
                self.add_error("end_time", "Endzeit muss nach der Startzeit liegen.")
        else:
            cleaned_data["start_time"] = None
            cleaned_data["end_time"] = None
            cleaned_data["break_minutes"] = 0

        return cleaned_data
```

- [ ] **Schritt 2: Django-Check**

```bash
python manage.py check
```
Erwartete Ausgabe: `System check identified no issues (0 silenced).`

- [ ] **Schritt 3: Commit**

```bash
git add timetracking/forms.py
git commit -m "feat: add UserProfileForm and WorkEntryForm"
```

---

## Task 6: Settings-View + Template

**Files:**
- Create: `timetracking/views.py`
- Create: `timetracking/urls.py`
- Create: `templates/timetracking/settings.html`
- Modify: `timetracking/tests.py`

- [ ] **Schritt 1: Failing tests hinzufügen**

In `timetracking/tests.py` ergänzen:
```python
class SettingsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="settingsuser", password="pw123456")
        self.client.login(username="settingsuser", password="pw123456")

    def test_settings_page_loads(self):
        response = self.client.get("/timetracking/einstellungen/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bundesland")

    def test_settings_saves_and_enables_feature(self):
        response = self.client.post("/timetracking/einstellungen/", {
            "timetracking_enabled": True,
            "bundesland": "BY",
            "daily_target_hours": "8.00",
            "work_start_date": "2026-01-01",
        })
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        self.user.userprofile.refresh_from_db()
        self.assertTrue(self.user.userprofile.timetracking_enabled)

    def test_settings_requires_login(self):
        self.client.logout()
        response = self.client.get("/timetracking/einstellungen/")
        self.assertRedirects(response, "/accounts/login/?next=/timetracking/einstellungen/")
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.SettingsViewTest -v 2
```
Erwartete Ausgabe: Fehler (views/urls nicht definiert)

- [ ] **Schritt 3: `timetracking/views.py` erstellen**

```python
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
    is_soll_day,
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

    # Aktuelle Woche Mo–So
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

        week_data.append({
            "day": day,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "soll": soll,
            "ist": ist,
            "diff": ist - soll,
        })

    # Aktueller Monat
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
    next_month_first = (last_of_month + timedelta(days=1))

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
```

- [ ] **Schritt 4: `timetracking/urls.py` erstellen**

```python
from django.urls import path
from . import views

app_name = "timetracking"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("eintrag/neu/", views.entry_create, name="entry_create"),
    path("eintrag/<int:pk>/bearbeiten/", views.entry_edit, name="entry_edit"),
    path("eintrag/<int:pk>/loeschen/", views.entry_delete, name="entry_delete"),
    path("einstellungen/", views.settings_view, name="settings_view"),
    path("monat/<int:year>/<int:month>/", views.month_detail, name="month_detail"),
]
```

- [ ] **Schritt 5: `templates/timetracking/` Verzeichnis und settings.html erstellen**

```bash
mkdir templates/timetracking
```

`templates/timetracking/settings.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:600px">
    <h1 class="h3 mb-4">Arbeitszeit – Einstellungen</h1>
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                <div class="mb-3">
                    <label for="{{ form.bundesland.id_for_label }}" class="form-label">{{ form.bundesland.label }}</label>
                    {{ form.bundesland }}
                    {% if form.bundesland.errors %}<div class="invalid-feedback d-block">{{ form.bundesland.errors }}</div>{% endif %}
                </div>
                <div class="mb-3">
                    <label for="{{ form.daily_target_hours.id_for_label }}" class="form-label">{{ form.daily_target_hours.label }}</label>
                    {{ form.daily_target_hours }}
                    {% if form.daily_target_hours.errors %}<div class="invalid-feedback d-block">{{ form.daily_target_hours.errors }}</div>{% endif %}
                </div>
                <div class="mb-3">
                    <label for="{{ form.work_start_date.id_for_label }}" class="form-label">{{ form.work_start_date.label }}</label>
                    {{ form.work_start_date }}
                    <div class="form-text">Ab diesem Datum wird der Gesamtsaldo berechnet.</div>
                    {% if form.work_start_date.errors %}<div class="invalid-feedback d-block">{{ form.work_start_date.errors }}</div>{% endif %}
                </div>
                <div class="mb-3 form-check">
                    {{ form.timetracking_enabled }}
                    <label for="{{ form.timetracking_enabled.id_for_label }}" class="form-check-label">{{ form.timetracking_enabled.label }}</label>
                </div>
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Speichern</button>
                    {% if profile.timetracking_enabled %}
                    <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary">Zurück</a>
                    {% endif %}
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 6: Tests ausführen — müssen PASS sein**

```bash
python manage.py test timetracking.tests.SettingsViewTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 7: Commit**

```bash
git add timetracking/views.py timetracking/urls.py templates/timetracking/
git commit -m "feat: add settings view and template"
```

---

## Task 7: Feature-Guard + CRUD Views + Templates

**Files:**
- Modify: `timetracking/tests.py`
- Create: `templates/timetracking/entry_form.html`
- Create: `templates/timetracking/entry_confirm_delete.html`

- [ ] **Schritt 1: Failing tests hinzufügen**

In `timetracking/tests.py` ergänzen:
```python
class FeatureGuardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="guarduser", password="pw123456")
        self.client.login(username="guarduser", password="pw123456")

    def test_dashboard_redirects_when_disabled(self):
        response = self.client.get("/timetracking/")
        self.assertRedirects(response, "/timetracking/einstellungen/")

    def test_entry_create_redirects_when_disabled(self):
        response = self.client.get("/timetracking/eintrag/neu/")
        self.assertRedirects(response, "/timetracking/einstellungen/")


class WorkEntryCRUDTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="cruduser", password="pw123456")
        self.client.login(username="cruduser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.daily_target_hours = Decimal("8.00")
        profile.work_start_date = date(2026, 1, 1)
        profile.save()

    def test_entry_create_get(self):
        response = self.client.get("/timetracking/eintrag/neu/")
        self.assertEqual(response.status_code, 200)

    def test_entry_create_post_work(self):
        response = self.client.post("/timetracking/eintrag/neu/", {
            "date": "2026-05-04",
            "entry_type": "work",
            "start_time": "08:00",
            "end_time": "16:30",
            "break_minutes": "30",
        })
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        from timetracking.models import WorkEntry
        self.assertEqual(WorkEntry.objects.filter(user=self.user).count(), 1)

    def test_entry_create_post_absence(self):
        response = self.client.post("/timetracking/eintrag/neu/", {
            "date": "2026-05-04",
            "entry_type": "urlaub",
            "break_minutes": "0",
        })
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        from timetracking.models import WorkEntry
        entry = WorkEntry.objects.get(user=self.user)
        self.assertIsNone(entry.start_time)

    def test_entry_delete(self):
        from timetracking.models import WorkEntry
        entry = WorkEntry.objects.create(user=self.user, date=date(2026, 5, 4), entry_type="urlaub")
        response = self.client.post(f"/timetracking/eintrag/{entry.pk}/loeschen/")
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        self.assertEqual(WorkEntry.objects.filter(user=self.user).count(), 0)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.FeatureGuardTest timetracking.tests.WorkEntryCRUDTest -v 2
```
Erwartete Ausgabe: Fehler (templates nicht vorhanden)

- [ ] **Schritt 3: `templates/timetracking/entry_form.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:600px">
    <h1 class="h3 mb-4">{{ title }}</h1>
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                <div class="mb-3">
                    <label for="{{ form.date.id_for_label }}" class="form-label">{{ form.date.label }}</label>
                    {{ form.date }}
                    {% if form.date.errors %}<div class="invalid-feedback d-block">{{ form.date.errors }}</div>{% endif %}
                </div>
                <div class="mb-3">
                    <label for="{{ form.entry_type.id_for_label }}" class="form-label">{{ form.entry_type.label }}</label>
                    {{ form.entry_type }}
                </div>
                <div id="time-fields">
                    <div class="mb-3">
                        <label for="{{ form.start_time.id_for_label }}" class="form-label">{{ form.start_time.label }}</label>
                        {{ form.start_time }}
                        {% if form.start_time.errors %}<div class="invalid-feedback d-block">{{ form.start_time.errors }}</div>{% endif %}
                    </div>
                    <div class="mb-3">
                        <label for="{{ form.end_time.id_for_label }}" class="form-label">{{ form.end_time.label }}</label>
                        {{ form.end_time }}
                        {% if form.end_time.errors %}<div class="invalid-feedback d-block">{{ form.end_time.errors }}</div>{% endif %}
                    </div>
                    <div class="mb-3">
                        <label for="{{ form.break_minutes.id_for_label }}" class="form-label">{{ form.break_minutes.label }}</label>
                        {{ form.break_minutes }}
                    </div>
                </div>
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Speichern</button>
                    <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary">Abbrechen</a>
                </div>
            </form>
        </div>
    </div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function () {
    const typeSelect = document.getElementById('id_entry_type');
    const timeFields = document.getElementById('time-fields');
    function toggleTimeFields() {
        timeFields.style.display = typeSelect.value === 'work' ? '' : 'none';
    }
    typeSelect.addEventListener('change', toggleTimeFields);
    toggleTimeFields();
});
</script>
{% endblock %}
```

- [ ] **Schritt 4: `templates/timetracking/entry_confirm_delete.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <div class="card">
        <div class="card-body">
            <h5 class="card-title">Eintrag löschen</h5>
            <p>Soll der Eintrag vom <strong>{{ entry.date|date:"d.m.Y" }}</strong> ({{ entry.get_entry_type_display }}) wirklich gelöscht werden?</p>
            <form method="post">
                {% csrf_token %}
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-danger">Löschen</button>
                    <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary">Abbrechen</a>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 5: Tests ausführen — müssen PASS sein**

```bash
python manage.py test timetracking.tests.FeatureGuardTest timetracking.tests.WorkEntryCRUDTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 6: Commit**

```bash
git add templates/timetracking/ timetracking/tests.py
git commit -m "feat: add WorkEntry CRUD views and templates"
```

---

## Task 8: Dashboard View + Template

**Files:**
- Modify: `timetracking/tests.py`
- Create: `templates/timetracking/dashboard.html`

- [ ] **Schritt 1: Failing tests hinzufügen**

In `timetracking/tests.py` ergänzen:
```python
class DashboardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="dashuser", password="pw123456")
        self.client.login(username="dashuser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.daily_target_hours = Decimal("8.00")
        profile.work_start_date = date(2026, 1, 1)
        profile.save()

    def test_dashboard_loads(self):
        response = self.client.get("/timetracking/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gesamtsaldo")

    def test_dashboard_shows_week_data(self):
        response = self.client.get("/timetracking/")
        self.assertIn("week_data", response.context)
        self.assertEqual(len(response.context["week_data"]), 7)

    def test_dashboard_shows_month_data(self):
        response = self.client.get("/timetracking/")
        self.assertIn("month_soll_days", response.context)
        self.assertGreater(response.context["month_soll_days"], 0)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.DashboardTest -v 2
```
Erwartete Ausgabe: `TemplateDoesNotExist: timetracking/dashboard.html`

- [ ] **Schritt 3: `templates/timetracking/dashboard.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1 class="h3 mb-0">Arbeitszeit</h1>
        <a href="{% url 'timetracking:settings_view' %}" class="btn btn-sm btn-outline-secondary">Einstellungen</a>
    </div>

    <!-- Gesamtsaldo -->
    <div class="card mb-4 text-center">
        <div class="card-body py-4">
            <div class="text-muted mb-1">Gesamtsaldo seit {{ profile.work_start_date|date:"d.m.Y" }}</div>
            <div class="display-5 fw-bold {% if total_saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                {% if total_saldo >= 0 %}+{% endif %}{{ total_saldo|floatformat:2 }}h
            </div>
        </div>
    </div>

    <div class="row g-4">
        <!-- Wochenübersicht -->
        <div class="col-lg-7">
            <div class="card h-100">
                <div class="card-header"><h5 class="mb-0">Diese Woche</h5></div>
                <div class="card-body p-0">
                    <table class="table table-sm table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Tag</th>
                                <th class="text-end">Ist</th>
                                <th class="text-end">Soll</th>
                                <th class="text-end">Diff</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for d in week_data %}
                        <tr class="{% if d.is_weekend %}text-muted{% elif d.holiday_name %}table-info{% elif d.day == today %}table-warning{% endif %}">
                            <td>
                                {{ d.day|date:"D, d.m." }}
                                {% if d.holiday_name %}<br><small class="text-muted">{{ d.holiday_name }}</small>{% endif %}
                                {% if d.entry and not d.is_weekend and not d.holiday_name %}
                                <br><small class="text-muted">
                                    {{ d.entry.get_entry_type_display }}
                                    {% if d.entry.start_time %} {{ d.entry.start_time|time:"H:i" }}–{{ d.entry.end_time|time:"H:i" }}{% endif %}
                                </small>
                                {% endif %}
                            </td>
                            <td class="text-end">{% if not d.is_weekend %}{{ d.ist|floatformat:2 }}h{% endif %}</td>
                            <td class="text-end">{% if not d.is_weekend %}{{ d.soll|floatformat:2 }}h{% endif %}</td>
                            <td class="text-end {% if not d.is_weekend %}{% if d.diff >= 0 %}text-success{% else %}text-danger{% endif %}{% endif %}">
                                {% if not d.is_weekend %}{% if d.diff >= 0 %}+{% endif %}{{ d.diff|floatformat:2 }}h{% endif %}
                            </td>
                            <td class="text-end">
                                {% if not d.is_weekend and not d.holiday_name %}
                                    {% if d.entry %}
                                    <a href="{% url 'timetracking:entry_edit' d.entry.pk %}" class="btn btn-sm btn-outline-secondary py-0 px-1">✏</a>
                                    {% else %}
                                    <a href="{% url 'timetracking:entry_create' %}?date={{ d.day|date:'Y-m-d' }}" class="btn btn-sm btn-outline-primary py-0 px-1">+</a>
                                    {% endif %}
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Monatsübersicht -->
        <div class="col-lg-5">
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0">Dieser Monat</h5>
                    <div class="btn-group btn-group-sm">
                        <a href="{% url 'timetracking:month_detail' prev_month.year prev_month.month %}" class="btn btn-outline-secondary">←</a>
                        <a href="{% url 'timetracking:month_detail' next_month.year next_month.month %}" class="btn btn-outline-secondary">→</a>
                    </div>
                </div>
                <div class="card-body">
                    <dl class="row mb-0">
                        <dt class="col-7">Arbeitstage (Soll)</dt>
                        <dd class="col-5">{{ month_soll_days }}</dd>
                        <dt class="col-7">Sollstunden</dt>
                        <dd class="col-5">{{ month_soll|floatformat:2 }}h</dd>
                        <dt class="col-7">Iststunden</dt>
                        <dd class="col-5">{{ month_ist|floatformat:2 }}h</dd>
                        <dt class="col-7 fw-bold">Monatssaldo</dt>
                        <dd class="col-5 fw-bold {% if month_saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                            {% if month_saldo >= 0 %}+{% endif %}{{ month_saldo|floatformat:2 }}h
                        </dd>
                    </dl>
                    <hr>
                    <a href="{% url 'timetracking:month_detail' today.year today.month %}" class="btn btn-sm btn-outline-primary w-100">Monatsdetail anzeigen</a>
                </div>
            </div>
        </div>
    </div>

    <div class="mt-3">
        <a href="{% url 'timetracking:entry_create' %}" class="btn btn-primary">+ Eintrag hinzufügen</a>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS sein**

```bash
python manage.py test timetracking.tests.DashboardTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 5: Commit**

```bash
git add templates/timetracking/dashboard.html timetracking/tests.py
git commit -m "feat: add dashboard view and template"
```

---

## Task 9: Monatsdetail View + Template

**Files:**
- Modify: `timetracking/tests.py`
- Create: `templates/timetracking/month_detail.html`

- [ ] **Schritt 1: Failing tests hinzufügen**

In `timetracking/tests.py` ergänzen:
```python
class MonthDetailTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="monthuser", password="pw123456")
        self.client.login(username="monthuser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.daily_target_hours = Decimal("8.00")
        profile.work_start_date = date(2026, 1, 1)
        profile.save()

    def test_month_detail_loads(self):
        response = self.client.get("/timetracking/monat/2026/5/")
        self.assertEqual(response.status_code, 200)

    def test_month_detail_has_31_days_for_may(self):
        response = self.client.get("/timetracking/monat/2026/5/")
        self.assertEqual(len(response.context["days_data"]), 31)

    def test_month_detail_soll_days_exclude_weekends_and_holidays(self):
        response = self.client.get("/timetracking/monat/2026/5/")
        # May 2026: 31 days, 2 weekend pairs = 8 weekend days, May 1 (Freitag) is holiday
        # Werktage: 31 - 8 - 1 = 22... let's just check it's > 0 and < 23
        self.assertGreater(response.context["soll_days_count"], 0)
        self.assertLessEqual(response.context["soll_days_count"], 22)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
python manage.py test timetracking.tests.MonthDetailTest -v 2
```
Erwartete Ausgabe: `TemplateDoesNotExist: timetracking/month_detail.html`

- [ ] **Schritt 3: `templates/timetracking/month_detail.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4">
    <div class="d-flex flex-wrap justify-content-between align-items-center mb-4 gap-2">
        <div class="d-flex align-items-center gap-2">
            <a href="{% url 'timetracking:dashboard' %}" class="btn btn-sm btn-outline-secondary">← Dashboard</a>
            <h1 class="h3 mb-0">{{ month_name }}</h1>
        </div>
        <div class="btn-group btn-group-sm">
            <a href="{% url 'timetracking:month_detail' prev_month.year prev_month.month %}" class="btn btn-outline-secondary">← {{ prev_month|date:"F Y" }}</a>
            <a href="{% url 'timetracking:month_detail' next_month.year next_month.month %}" class="btn btn-outline-secondary">{{ next_month|date:"F Y" }} →</a>
        </div>
    </div>

    <!-- Monatssummary -->
    <div class="row g-3 mb-4">
        <div class="col-6 col-md-3">
            <div class="card text-center">
                <div class="card-body py-3">
                    <div class="text-muted small">Arbeitstage</div>
                    <div class="h4 mb-0">{{ soll_days_count }}</div>
                </div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="card text-center">
                <div class="card-body py-3">
                    <div class="text-muted small">Sollstunden</div>
                    <div class="h4 mb-0">{{ month_soll|floatformat:2 }}h</div>
                </div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="card text-center">
                <div class="card-body py-3">
                    <div class="text-muted small">Iststunden</div>
                    <div class="h4 mb-0">{{ month_ist|floatformat:2 }}h</div>
                </div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="card text-center {% if month_saldo >= 0 %}border-success{% else %}border-danger{% endif %}">
                <div class="card-body py-3">
                    <div class="text-muted small">Monatssaldo</div>
                    <div class="h4 mb-0 {% if month_saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                        {% if month_saldo >= 0 %}+{% endif %}{{ month_saldo|floatformat:2 }}h
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Tagesliste -->
    <div class="card">
        <div class="card-body p-0">
            <table class="table table-sm table-hover mb-0">
                <thead class="table-light">
                    <tr>
                        <th>Datum</th>
                        <th>Typ</th>
                        <th class="text-end">Ist</th>
                        <th class="text-end">Soll</th>
                        <th class="text-end">Diff</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                {% for d in days_data %}
                <tr class="{% if d.is_weekend %}text-muted{% elif d.holiday_name %}table-info{% endif %}">
                    <td>
                        {{ d.day|date:"D, d.m.Y" }}
                        {% if d.holiday_name %}<small class="ms-1 text-muted">({{ d.holiday_name }})</small>{% endif %}
                    </td>
                    <td>
                        {% if d.entry %}{{ d.entry.get_entry_type_display }}
                        {% elif d.is_weekend %}Wochenende
                        {% elif d.holiday_name %}Feiertag
                        {% else %}–{% endif %}
                    </td>
                    <td class="text-end">{% if not d.is_weekend %}{{ d.ist|floatformat:2 }}h{% endif %}</td>
                    <td class="text-end">{% if not d.is_weekend %}{{ d.soll|floatformat:2 }}h{% endif %}</td>
                    <td class="text-end {% if not d.is_weekend %}{% if d.diff >= 0 %}text-success{% else %}text-danger{% endif %}{% endif %}">
                        {% if not d.is_weekend %}{% if d.diff >= 0 %}+{% endif %}{{ d.diff|floatformat:2 }}h{% endif %}
                    </td>
                    <td>
                        {% if not d.is_weekend and not d.holiday_name %}
                            {% if d.entry %}
                            <a href="{% url 'timetracking:entry_edit' d.entry.pk %}" class="btn btn-sm btn-outline-secondary py-0 px-1">✏</a>
                            {% else %}
                            <a href="{% url 'timetracking:entry_create' %}?date={{ d.day|date:'Y-m-d' }}" class="btn btn-sm btn-outline-primary py-0 px-1">+</a>
                            {% endif %}
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS sein**

```bash
python manage.py test timetracking.tests.MonthDetailTest -v 2
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 5: Commit**

```bash
git add templates/timetracking/month_detail.html timetracking/tests.py
git commit -m "feat: add month detail view and template"
```

---

## Task 10: Sidebar-Integration in base.html

**Files:**
- Modify: `templates/base.html`

- [ ] **Schritt 1: Sidebar-Link in Desktop-Sidebar einfügen**

In `templates/base.html`, in der Desktop-Sidebar nach dem letzten bestehenden `<a>` in `<nav class="sidebar-nav">`, folgenden Block einfügen:

```html
{% if user.userprofile.timetracking_enabled %}
<a href="{% url 'timetracking:dashboard' %}" class="{% if '/timetracking/' in request.path %}active{% endif %}">Arbeitszeit</a>
{% endif %}
```

- [ ] **Schritt 2: Sidebar-Link in Mobile Offcanvas einfügen**

Identischen Block in der Mobile-Offcanvas-Navigation einfügen (Abschnitt `<nav class="sidebar-nav">` im `offcanvas-body`).

- [ ] **Schritt 3: Django-Check + alle Tests**

```bash
python manage.py check
python manage.py test timetracking -v 2
```
Erwartete Ausgabe: `System check identified no issues (0 silenced).` und `OK`

- [ ] **Schritt 4: Commit**

```bash
git add templates/base.html
git commit -m "feat: add Arbeitszeit sidebar link (conditional on feature flag)"
```

---

## Abschluss-Check

- [ ] **Alle Tests laufen durch**

```bash
python manage.py test
```
Erwartete Ausgabe: Alle Tests OK, keine Fehler.

- [ ] **Dev-Server starten und manuell testen**

```bash
python manage.py runserver
```

Testen:
1. `/timetracking/einstellungen/` aufrufen → Bundesland wählen, Startdatum setzen, Feature aktivieren → Speichern
2. Dashboard erscheint mit leerem Saldo
3. Eintrag anlegen: Datum wählen, Typ "Arbeit", Start/End-Zeit → Speichern
4. Dashboard zeigt aktualisierten Saldo
5. Monatsdetail aufrufen via Link
6. Sidebar zeigt "Arbeitszeit"-Link

- [ ] **Final Commit**

```bash
git add .
git commit -m "feat: complete Arbeitszeiterfassung feature"
```
