# Timetracking Multi-Job + Monatsbericht Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Erweitert die Arbeitszeiterfassung um mehrere benannte Jobs mit Wochensoll, Job-Switcher, und monatlichen Arbeitszeitzeugnissen als druckbares HTML, PDF-Download und E-Mail.

**Architecture:** Neues `Job`-Model (ForeignKey→User) ersetzt die bisherigen `daily_target_hours`/`work_start_date`-Felder in `UserProfile`. `WorkEntry` bekommt einen ForeignKey auf `Job`. Das Saldo wird wöchentlich statt täglich berechnet. Bestehende Daten werden per Datenmigration in einen automatisch erstellten "Hauptjob" überführt. WeasyPrint generiert PDFs aus HTML-Templates.

**Tech Stack:** Django 6, Bootstrap 5.3, WeasyPrint (HTML→PDF), django.core.mail (E-Mail)

---

## File Map

**Modify:**
- `requirements.txt` — WeasyPrint
- `timetracking/models.py` — Job-Model hinzufügen, UserProfile anpassen, WorkEntry job-FK
- `timetracking/migrations/` — Schema + Data Migrations (auto-generiert + manuell)
- `timetracking/utils.py` — Saldo-Berechnung auf wöchentlich umstellen, get_week_start
- `timetracking/forms.py` — JobForm, WorkEntryForm (job-Feld), UserProfileForm (old fields entfernen)
- `timetracking/views.py` — job_list, job_create, job_edit, job_delete, job_activate, report_view, report_pdf, report_email; dashboard/entry_create/entry_edit/settings_view anpassen
- `timetracking/urls.py` — neue URL-Patterns
- `timetracking/admin.py` — Job registrieren
- `timetracking/tests.py` — Tests aktualisieren + neue Tests

**Create:**
- `templates/timetracking/job_list.html`
- `templates/timetracking/job_form.html`
- `templates/timetracking/job_confirm_delete.html`
- `templates/timetracking/report.html`

**Modify (Templates):**
- `templates/timetracking/dashboard.html` — Job-Switcher
- `templates/timetracking/entry_form.html` — Job-Dropdown
- `templates/timetracking/settings.html` — alte Felder entfernen
- `templates/timetracking/month_detail.html` — Link zu Bericht

---

## Task 1: WeasyPrint installieren

**Files:** `requirements.txt`

- [ ] **Schritt 1: WeasyPrint hinzufügen**

Füge am Ende von `/home/stefan/Projekte/Wochi/requirements.txt` ein:
```
weasyprint
```

- [ ] **Schritt 2: Installieren**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && pip install weasyprint
```
Erwartete Ausgabe: `Successfully installed weasyprint-...`

- [ ] **Schritt 3: Django-Check**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py check
```
Erwartete Ausgabe: `System check identified no issues (0 silenced).`

- [ ] **Schritt 4: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add requirements.txt && git commit -m "feat: add weasyprint dependency"
```

---

## Task 2: Job Model + Schema-Migrationen

**Files:**
- Modify: `timetracking/models.py`
- Modify: `timetracking/admin.py`
- Modify: `timetracking/tests.py`
- Create: `timetracking/migrations/0003_*.py` (auto)
- Create: `timetracking/migrations/0004_*.py` (auto)

- [ ] **Schritt 1: Failing tests schreiben**

Ersetze die Klasse `UserProfileSignalTest` und `WorkEntryTest` komplett in `/home/stefan/Projekte/Wochi/timetracking/tests.py` (Zeilen 10–55):

```python
class UserProfileSignalTest(TestCase):
    def test_profile_created_on_user_creation(self):
        user = User.objects.create_user(username="testuser", password="pw123456")
        self.assertTrue(hasattr(user, "userprofile"))
        self.assertFalse(user.userprofile.timetracking_enabled)

    def test_profile_not_duplicated_on_save(self):
        user = User.objects.create_user(username="testuser2", password="pw123456")
        user.save()
        from timetracking.models import UserProfile
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_job_creation(self):
        from timetracking.models import Job
        user = User.objects.create_user(username="jobtest", password="pw123456")
        job = Job.objects.create(
            user=user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        self.assertEqual(str(job), "Hauptjob (jobtest)")
        self.assertEqual(job.weekly_target_hours, Decimal("40.00"))

    def test_job_unique_name_per_user(self):
        from timetracking.models import Job
        from django.db import IntegrityError
        user = User.objects.create_user(username="duptest", password="pw123456")
        Job.objects.create(user=user, name="Hauptjob", weekly_target_hours=Decimal("40.00"), work_start_date=date(2026, 1, 1))
        with self.assertRaises(IntegrityError):
            Job.objects.create(user=user, name="Hauptjob", weekly_target_hours=Decimal("20.00"), work_start_date=date(2026, 1, 1))


class WorkEntryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="worker", password="pw123456")
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )

    def test_worked_hours_calculation(self):
        from timetracking.models import WorkEntry
        from datetime import time
        entry = WorkEntry.objects.create(
            user=self.user,
            job=self.job,
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
            job=self.job,
            date=date(2026, 5, 4),
            entry_type="urlaub",
        )
        self.assertIsNone(entry.worked_hours)

    def test_unique_entry_per_day(self):
        from timetracking.models import WorkEntry
        from django.db import IntegrityError
        WorkEntry.objects.create(user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="urlaub")
        with self.assertRaises(IntegrityError):
            WorkEntry.objects.create(user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="krankheit")
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.UserProfileSignalTest timetracking.tests.WorkEntryTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: Job-Model zu `timetracking/models.py` hinzufügen**

Füge nach `BUNDESLAND_CHOICES` und vor `class UserProfile` ein:

```python
class Job(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    name = models.CharField(max_length=100)
    weekly_target_hours = models.DecimalField(max_digits=5, decimal_places=2)
    work_start_date = models.DateField()

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"
```

- [ ] **Schritt 4: `UserProfile` anpassen**

Ersetze in `timetracking/models.py` die `UserProfile`-Klasse:

```python
class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="userprofile",
    )
    timetracking_enabled = models.BooleanField(default=False)
    bundesland = models.CharField(max_length=2, choices=BUNDESLAND_CHOICES, default="BY")
    active_job = models.ForeignKey(
        "Job",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_for_profiles",
    )
    # Legacy fields kept temporarily for data migration — removed in Task 3
    daily_target_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("8.00"))
    work_start_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Profile({self.user.username})"
```

- [ ] **Schritt 5: `WorkEntry` — job-FK hinzufügen**

Füge in `WorkEntry` nach dem `user`-Feld ein (nullable zunächst):

```python
    job = models.ForeignKey(
        "Job",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="entries",
    )
```

- [ ] **Schritt 6: admin.py aktualisieren**

Ersetze den Inhalt von `/home/stefan/Projekte/Wochi/timetracking/admin.py`:

```python
from django.contrib import admin
from .models import Job, UserProfile, WorkEntry


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "weekly_target_hours", "work_start_date"]
    list_filter = ["user"]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timetracking_enabled", "bundesland", "active_job"]


@admin.register(WorkEntry)
class WorkEntryAdmin(admin.ModelAdmin):
    list_display = ["user", "job", "date", "entry_type", "start_time", "end_time", "break_minutes"]
    list_filter = ["entry_type", "job", "user"]
```

- [ ] **Schritt 7: Migrationen erstellen und anwenden**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py makemigrations timetracking && python manage.py migrate
```
Erwartete Ausgabe: zwei neue Migrationsdateien, beide angewendet.

- [ ] **Schritt 8: Tests ausführen — müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.UserProfileSignalTest timetracking.tests.WorkEntryTest -v 2 2>&1 | tail -15
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 9: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/ && git commit -m "feat: add Job model and job FK to WorkEntry"
```

---

## Task 3: Datenmigration (bestehende Daten → Job "Hauptjob")

**Files:**
- Create: `timetracking/migrations/0005_migrate_job_data.py` (manuell)

- [ ] **Schritt 1: Datenmigrations-Datei erstellen**

Erstelle `/home/stefan/Projekte/Wochi/timetracking/migrations/0005_migrate_job_data.py`:

```python
from django.db import migrations
from decimal import Decimal
from datetime import date as date_type


def migrate_job_data(apps, schema_editor):
    UserProfile = apps.get_model("timetracking", "UserProfile")
    Job = apps.get_model("timetracking", "Job")
    WorkEntry = apps.get_model("timetracking", "WorkEntry")

    for profile in UserProfile.objects.select_related("user").all():
        daily_hours = profile.daily_target_hours or Decimal("8.00")
        weekly_hours = daily_hours * 5
        start_date = profile.work_start_date or date_type.today()

        job, _ = Job.objects.get_or_create(
            user=profile.user,
            name="Hauptjob",
            defaults={
                "weekly_target_hours": weekly_hours,
                "work_start_date": start_date,
            },
        )
        WorkEntry.objects.filter(user=profile.user, job__isnull=True).update(job=job)
        profile.active_job = job
        profile.save(update_fields=["active_job"])


def reverse_migrate_job_data(apps, schema_editor):
    WorkEntry = apps.get_model("timetracking", "WorkEntry")
    WorkEntry.objects.all().update(job=None)


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0003_job_userprofile_active_job_workentry_job"),
    ]

    operations = [
        migrations.RunPython(migrate_job_data, reverse_migrate_job_data),
    ]
```

**WICHTIG:** Passe die `dependencies`-Zeile an die tatsächlich erstellten Migrationsdateinamen aus Task 2 an. Prüfe mit:
```bash
ls /home/stefan/Projekte/Wochi/timetracking/migrations/
```

- [ ] **Schritt 2: Migration anwenden**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py migrate timetracking
```
Erwartete Ausgabe: `Applying timetracking.0005_migrate_job_data... OK`

- [ ] **Schritt 3: Prüfen**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py shell -c "
from timetracking.models import Job, WorkEntry
print('Jobs:', Job.objects.count())
print('Entries without job:', WorkEntry.objects.filter(job__isnull=True).count())
"
```
Erwartete Ausgabe: `Entries without job: 0`

- [ ] **Schritt 4: Tests laufen lassen**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking -v 0 2>&1 | tail -5
```
Erwartete Ausgabe: Tests laufen durch (evtl. Failures wegen alter Settings-Tests — werden in Task 7 gefixt).

- [ ] **Schritt 5: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/migrations/ && git commit -m "feat: data migration — create default Hauptjob for existing users"
```

---

## Task 4: Wöchentliche Saldo-Utilities

**Files:**
- Modify: `timetracking/utils.py`
- Modify: `timetracking/tests.py` (HolidayUtilsTest ersetzen)

- [ ] **Schritt 1: Failing tests schreiben**

Ersetze die Klasse `HolidayUtilsTest` komplett in `tests.py`:

```python
class HolidayUtilsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="utilsuser", password="pw123456")
        self.user.userprofile.bundesland = "BY"
        self.user.userprofile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 5, 4),
        )

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
        days = get_soll_days_in_range(date(2026, 5, 4), date(2026, 5, 8), "BY")
        self.assertEqual(len(days), 5)

    def test_weekly_saldo_positive(self):
        from timetracking.utils import calculate_total_saldo
        from timetracking.models import WorkEntry
        from datetime import time
        # Week of May 4–8: 40h soll, worked 9h/day × 5 = 45h
        for day_offset in range(5):
            d = date(2026, 5, 4 + day_offset)
            WorkEntry.objects.create(
                user=self.user,
                job=self.job,
                date=d,
                entry_type="work",
                start_time=time(8, 0),
                end_time=time(17, 0),
                break_minutes=0,
            )
        # as_of = May 11 (next week Monday): week of May 4 is complete
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("5.00"))  # 45h - 40h = +5h

    def test_weekly_saldo_absence_counts_as_daily_equiv(self):
        from timetracking.utils import calculate_total_saldo
        from timetracking.models import WorkEntry
        # Full week of urlaub = soll fulfilled exactly
        for day_offset in range(5):
            d = date(2026, 5, 4 + day_offset)
            WorkEntry.objects.create(
                user=self.user,
                job=self.job,
                date=d,
                entry_type="urlaub",
            )
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("0.00"))

    def test_current_week_no_entries_no_deficit(self):
        from timetracking.utils import calculate_weekly_saldo
        from timetracking.utils import get_week_start
        # work_start_date = today's week, no entries → saldo = 0 (no deficit yet)
        today = date.today()
        self.job.work_start_date = get_week_start(today)
        self.job.save()
        weeks = calculate_weekly_saldo(self.job, "BY")
        if weeks:
            current = next((w for w in weeks if w["is_current"]), None)
            if current:
                self.assertEqual(current["saldo"], Decimal("0.00"))
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.HolidayUtilsTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: `timetracking/utils.py` komplett ersetzen**

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

    current_week_start = get_week_start(date.today())
    weeks = []
    week_start = get_week_start(job.work_start_date)

    while week_start <= get_week_start(as_of):
        week_end = week_start + timedelta(days=6)
        effective_start = max(week_start, job.work_start_date)
        effective_end = min(week_end, as_of)

        # Soll proportional: effective soll days / full-week soll days
        full_week_fri = week_start + timedelta(days=4)
        full_soll = len(get_soll_days_in_range(week_start, full_week_fri, bundesland))
        eff_soll = len(get_soll_days_in_range(effective_start, effective_end, bundesland))

        if full_soll > 0:
            week_soll = job.weekly_target_hours * Decimal(eff_soll) / Decimal(full_soll)
        else:
            week_soll = Decimal("0")

        entries = WorkEntry.objects.filter(job=job, date__range=[effective_start, effective_end])
        daily_equiv = job.weekly_target_hours / Decimal("5")

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
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.HolidayUtilsTest -v 2 2>&1 | tail -15
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 5: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/utils.py timetracking/tests.py && git commit -m "feat: weekly saldo calculation replacing daily model"
```

---

## Task 5: Job Forms + CRUD Views + URLs

**Files:**
- Modify: `timetracking/forms.py`
- Modify: `timetracking/views.py`
- Modify: `timetracking/urls.py`
- Modify: `timetracking/tests.py` (JobCRUDTest hinzufügen)

- [ ] **Schritt 1: Failing tests hinzufügen**

Füge am Ende von `timetracking/tests.py` hinzu:

```python
class JobCRUDTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="jobcrud", password="pw123456")
        self.client.login(username="jobcrud", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_job_list_loads(self):
        response = self.client.get("/timetracking/jobs/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hauptjob")

    def test_job_create(self):
        response = self.client.post("/timetracking/jobs/neu/", {
            "name": "Nebenjob",
            "weekly_target_hours": "20.00",
            "work_start_date": "2026-03-01",
        })
        self.assertRedirects(response, "/timetracking/jobs/", fetch_redirect_response=False)
        from timetracking.models import Job
        self.assertEqual(Job.objects.filter(user=self.user).count(), 2)

    def test_job_activate(self):
        from timetracking.models import Job
        job2 = Job.objects.create(
            user=self.user, name="Nebenjob",
            weekly_target_hours=Decimal("20.00"), work_start_date=date(2026, 3, 1)
        )
        response = self.client.post(f"/timetracking/jobs/{job2.pk}/aktivieren/")
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.userprofile.active_job, job2)

    def test_job_delete_blocked_with_entries(self):
        from timetracking.models import WorkEntry
        WorkEntry.objects.create(user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="urlaub")
        response = self.client.post(f"/timetracking/jobs/{self.job.pk}/loeschen/")
        from timetracking.models import Job
        self.assertEqual(Job.objects.filter(user=self.user).count(), 1)

    def test_job_delete_allowed_without_entries(self):
        from timetracking.models import Job
        job2 = Job.objects.create(
            user=self.user, name="Leerjob",
            weekly_target_hours=Decimal("10.00"), work_start_date=date(2026, 5, 1)
        )
        response = self.client.post(f"/timetracking/jobs/{job2.pk}/loeschen/")
        self.assertRedirects(response, "/timetracking/jobs/", fetch_redirect_response=False)
        self.assertEqual(Job.objects.filter(user=self.user, name="Leerjob").count(), 0)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.JobCRUDTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: `JobForm` zu `forms.py` hinzufügen**

Füge oben in `timetracking/forms.py` nach den Imports ein:

```python
from .models import Job, UserProfile, WorkEntry


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ["name", "weekly_target_hours", "work_start_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "weekly_target_hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.5"}),
            "work_start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
        }
        labels = {
            "name": "Bezeichnung",
            "weekly_target_hours": "Wochensoll (Stunden)",
            "work_start_date": "Startdatum für Saldo",
        }
```

Ersetze auch die erste Zeile `from .models import UserProfile, WorkEntry` durch `from .models import Job, UserProfile, WorkEntry`.

- [ ] **Schritt 4: Job-Views zu `views.py` hinzufügen**

Füge nach dem `settings_view` folgende Views in `timetracking/views.py` ein:

```python
@login_required
def job_list(request):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")
    jobs = request.user.jobs.annotate_entry_count() if hasattr(request.user.jobs, 'annotate_entry_count') else request.user.jobs.all()
    from django.db.models import Count
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
            messages.success(request, f"Job „{job.name}" wurde erstellt.")
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
            messages.error(request, f"Job „{job.name}" kann nicht gelöscht werden, da noch Einträge vorhanden sind.")
            return redirect("timetracking:job_list")
        job.delete()
        if profile.active_job_id == pk:
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
```

- [ ] **Schritt 5: `timetracking/urls.py` aktualisieren**

Ersetze den Inhalt von `timetracking/urls.py`:

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
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/neu/", views.job_create, name="job_create"),
    path("jobs/<int:pk>/bearbeiten/", views.job_edit, name="job_edit"),
    path("jobs/<int:pk>/loeschen/", views.job_delete, name="job_delete"),
    path("jobs/<int:pk>/aktivieren/", views.job_activate, name="job_activate"),
    path("bericht/<int:year>/<int:month>/", views.report_view, name="report_view"),
    path("bericht/<int:year>/<int:month>/pdf/", views.report_pdf, name="report_pdf"),
    path("bericht/<int:year>/<int:month>/email/", views.report_email, name="report_email"),
]
```

- [ ] **Schritt 6: Stub-Views für report_view/pdf/email hinzufügen** (damit URLs nicht brechen)

Füge am Ende von `views.py` ein:

```python
@login_required
def report_view(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")
    return render(request, "timetracking/report.html", {"year": year, "month": month})


@login_required
def report_pdf(request, year, month):
    return redirect("timetracking:report_view", year=year, month=month)


@login_required
def report_email(request, year, month):
    return redirect("timetracking:report_view", year=year, month=month)
```

- [ ] **Schritt 7: Tests ausführen — müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.JobCRUDTest -v 2 2>&1 | tail -15
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 8: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/ && git commit -m "feat: add Job CRUD views and URLs"
```

---

## Task 6: Job Templates

**Files:**
- Create: `templates/timetracking/job_list.html`
- Create: `templates/timetracking/job_form.html`
- Create: `templates/timetracking/job_confirm_delete.html`
- Create: `templates/timetracking/report.html` (Stub)

- [ ] **Schritt 1: `templates/timetracking/job_list.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:700px">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1 class="h3 mb-0">Jobs verwalten</h1>
        <a href="{% url 'timetracking:job_create' %}" class="btn btn-primary btn-sm">+ Neuer Job</a>
    </div>
    {% if jobs %}
    <div class="list-group">
        {% for job in jobs %}
        <div class="list-group-item d-flex justify-content-between align-items-center">
            <div>
                <div class="fw-bold">
                    {{ job.name }}
                    {% if job == profile.active_job %}<span class="badge bg-success ms-2">Aktiv</span>{% endif %}
                </div>
                <small class="text-muted">
                    Wochensoll: {{ job.weekly_target_hours }}h &middot;
                    Start: {{ job.work_start_date|date:"d.m.Y" }} &middot;
                    {{ job.entry_count }} Eintrag{% if job.entry_count != 1 %}e{% endif %}
                </small>
            </div>
            <div class="d-flex gap-1">
                {% if job != profile.active_job %}
                <form method="post" action="{% url 'timetracking:job_activate' job.pk %}">
                    {% csrf_token %}
                    <button class="btn btn-sm btn-outline-success">Aktivieren</button>
                </form>
                {% endif %}
                <a href="{% url 'timetracking:job_edit' job.pk %}" class="btn btn-sm btn-outline-secondary">&#9998;</a>
                <a href="{% url 'timetracking:job_delete' job.pk %}" class="btn btn-sm btn-outline-danger">&#10005;</a>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p class="text-muted">Noch keine Jobs vorhanden.</p>
    {% endif %}
    <div class="mt-3">
        <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary btn-sm">← Dashboard</a>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 2: `templates/timetracking/job_form.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <h1 class="h3 mb-4">{{ title }}</h1>
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                <div class="mb-3">
                    <label for="{{ form.name.id_for_label }}" class="form-label">{{ form.name.label }}</label>
                    {{ form.name }}
                    {% if form.name.errors %}<div class="invalid-feedback d-block">{{ form.name.errors }}</div>{% endif %}
                </div>
                <div class="mb-3">
                    <label for="{{ form.weekly_target_hours.id_for_label }}" class="form-label">{{ form.weekly_target_hours.label }}</label>
                    {{ form.weekly_target_hours }}
                    {% if form.weekly_target_hours.errors %}<div class="invalid-feedback d-block">{{ form.weekly_target_hours.errors }}</div>{% endif %}
                </div>
                <div class="mb-3">
                    <label for="{{ form.work_start_date.id_for_label }}" class="form-label">{{ form.work_start_date.label }}</label>
                    {{ form.work_start_date }}
                    <div class="form-text">Ab diesem Datum wird der Saldo für diesen Job berechnet.</div>
                    {% if form.work_start_date.errors %}<div class="invalid-feedback d-block">{{ form.work_start_date.errors }}</div>{% endif %}
                </div>
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Speichern</button>
                    <a href="{% url 'timetracking:job_list' %}" class="btn btn-outline-secondary">Abbrechen</a>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 3: `templates/timetracking/job_confirm_delete.html` erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <div class="card">
        <div class="card-body">
            <h5 class="card-title">Job löschen</h5>
            <p>Soll der Job <strong>{{ job.name }}</strong> wirklich gelöscht werden?</p>
            {% if job.entries.exists %}
            <div class="alert alert-danger">Dieser Job hat noch Einträge und kann nicht gelöscht werden.</div>
            <a href="{% url 'timetracking:job_list' %}" class="btn btn-secondary">Zurück</a>
            {% else %}
            <form method="post">
                {% csrf_token %}
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-danger">Löschen</button>
                    <a href="{% url 'timetracking:job_list' %}" class="btn btn-outline-secondary">Abbrechen</a>
                </div>
            </form>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 4: `templates/timetracking/report.html` Stub erstellen**

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4">
    <h1 class="h3">Monatsbericht {{ year }}/{{ month }}</h1>
    <p class="text-muted">Wird in Task 10 implementiert.</p>
    <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary">← Dashboard</a>
</div>
{% endblock %}
```

- [ ] **Schritt 5: Django-Check + Tests**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py check && python manage.py test timetracking.tests.JobCRUDTest -v 0 2>&1 | tail -5
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 6: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add templates/timetracking/ && git commit -m "feat: add job management templates"
```

---

## Task 7: WorkEntryForm + Views anpassen (Job-Feld)

**Files:**
- Modify: `timetracking/forms.py`
- Modify: `timetracking/views.py`
- Modify: `timetracking/tests.py` (WorkEntryCRUDTest + FeatureGuardTest + SettingsViewTest aktualisieren)

- [ ] **Schritt 1: `WorkEntryForm` aktualisieren**

Ersetze die Klasse `WorkEntryForm` in `forms.py`:

```python
class WorkEntryForm(forms.ModelForm):
    class Meta:
        model = WorkEntry
        fields = ["job", "date", "entry_type", "start_time", "end_time", "break_minutes"]
        widgets = {
            "job": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "entry_type": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "break_minutes": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }
        labels = {
            "job": "Job",
            "date": "Datum",
            "entry_type": "Typ",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
            "break_minutes": "Pause (Minuten)",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["job"].queryset = Job.objects.filter(user=user)

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

- [ ] **Schritt 2: `entry_create` und `entry_edit` in `views.py` anpassen**

Ersetze `entry_create`:

```python
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
        form = WorkEntryForm(request.POST, user=request.user)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Eintrag gespeichert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(initial=initial, user=request.user)

    return render(request, "timetracking/entry_form.html", {"form": form, "title": "Neuer Eintrag"})
```

Ersetze `entry_edit`:

```python
@login_required
def entry_edit(request, pk):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled:
        return redirect("timetracking:settings_view")

    entry = get_object_or_404(WorkEntry, pk=pk, user=request.user)

    if request.method == "POST":
        form = WorkEntryForm(request.POST, instance=entry, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Eintrag aktualisiert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(instance=entry, user=request.user)

    return render(request, "timetracking/entry_form.html", {"form": form, "title": "Eintrag bearbeiten"})
```

- [ ] **Schritt 3: Tests in `tests.py` aktualisieren**

Ersetze `SettingsViewTest`:

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
        })
        self.assertRedirects(response, "/timetracking/jobs/", fetch_redirect_response=False)
        self.user.userprofile.refresh_from_db()
        self.assertTrue(self.user.userprofile.timetracking_enabled)

    def test_settings_requires_login(self):
        self.client.logout()
        response = self.client.get("/timetracking/einstellungen/")
        self.assertRedirects(response, "/accounts/login/?next=/timetracking/einstellungen/")
```

Ersetze `FeatureGuardTest`:

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
```

Ersetze `WorkEntryCRUDTest`:

```python
class WorkEntryCRUDTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="cruduser", password="pw123456")
        self.client.login(username="cruduser", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_entry_create_get(self):
        response = self.client.get("/timetracking/eintrag/neu/")
        self.assertEqual(response.status_code, 200)

    def test_entry_create_post_work(self):
        response = self.client.post("/timetracking/eintrag/neu/", {
            "job": self.job.pk,
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
            "job": self.job.pk,
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
        entry = WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="urlaub"
        )
        response = self.client.post(f"/timetracking/eintrag/{entry.pk}/loeschen/")
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        self.assertEqual(WorkEntry.objects.filter(user=self.user).count(), 0)
```

- [ ] **Schritt 4: `entry_form.html` — Job-Feld ergänzen**

Füge in `templates/timetracking/entry_form.html` nach `{% csrf_token %}` und vor dem Datum-Block ein:

```html
                <div class="mb-3">
                    <label for="{{ form.job.id_for_label }}" class="form-label">{{ form.job.label }}</label>
                    {{ form.job }}
                </div>
```

- [ ] **Schritt 5: Tests ausführen — müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.WorkEntryCRUDTest timetracking.tests.FeatureGuardTest timetracking.tests.SettingsViewTest -v 2 2>&1 | tail -15
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 6: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/ templates/timetracking/entry_form.html && git commit -m "feat: add job field to WorkEntry form and views"
```

---

## Task 8: Settings + UserProfileForm bereinigen

**Files:**
- Modify: `timetracking/forms.py`
- Modify: `timetracking/views.py` (settings_view)
- Modify: `templates/timetracking/settings.html`

- [ ] **Schritt 1: `UserProfileForm` aktualisieren**

Ersetze `UserProfileForm` in `forms.py`:

```python
class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["timetracking_enabled", "bundesland"]
        widgets = {
            "bundesland": forms.Select(attrs={"class": "form-select"}),
            "timetracking_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "timetracking_enabled": "Arbeitszeiterfassung aktivieren",
            "bundesland": "Bundesland (für Feiertage, gilt für alle Jobs)",
        }
```

- [ ] **Schritt 2: `settings_view` anpassen — Redirect nach Jobs wenn kein active_job**

Ersetze `settings_view` in `views.py`:

```python
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
```

- [ ] **Schritt 3: `settings.html` aktualisieren**

Ersetze den Inhalt von `templates/timetracking/settings.html`:

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
                <div class="mb-3 form-check">
                    {{ form.timetracking_enabled }}
                    <label for="{{ form.timetracking_enabled.id_for_label }}" class="form-check-label">{{ form.timetracking_enabled.label }}</label>
                </div>
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Speichern</button>
                    {% if profile.timetracking_enabled and profile.active_job %}
                    <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary">Zurück</a>
                    {% endif %}
                </div>
            </form>
        </div>
    </div>
    {% if profile.timetracking_enabled %}
    <div class="mt-3">
        <a href="{% url 'timetracking:job_list' %}" class="btn btn-outline-primary btn-sm">Jobs verwalten →</a>
    </div>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Schritt 4: Tests ausführen**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.SettingsViewTest -v 2 2>&1 | tail -10
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 5: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/forms.py timetracking/views.py templates/timetracking/settings.html && git commit -m "feat: simplify settings — job-specific config moved to Job model"
```

---

## Task 9: Dashboard — Job-Switcher + Wochensaldo

**Files:**
- Modify: `timetracking/views.py` (dashboard)
- Modify: `templates/timetracking/dashboard.html`
- Modify: `timetracking/tests.py` (DashboardTest + MonthDetailTest aktualisieren)

- [ ] **Schritt 1: Tests aktualisieren**

Ersetze `DashboardTest` und `MonthDetailTest`:

```python
class DashboardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="dashuser", password="pw123456")
        self.client.login(username="dashuser", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_dashboard_loads(self):
        response = self.client.get("/timetracking/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gesamtsaldo")
        self.assertContains(response, "Hauptjob")

    def test_dashboard_shows_week_data(self):
        response = self.client.get("/timetracking/")
        self.assertIn("week_data", response.context)
        self.assertEqual(len(response.context["week_data"]), 7)

    def test_dashboard_shows_active_job(self):
        response = self.client.get("/timetracking/")
        self.assertEqual(response.context["active_job"], self.job)


class MonthDetailTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="monthuser", password="pw123456")
        self.client.login(username="monthuser", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_month_detail_loads(self):
        response = self.client.get("/timetracking/monat/2026/5/")
        self.assertEqual(response.status_code, 200)

    def test_month_detail_has_31_days_for_may(self):
        response = self.client.get("/timetracking/monat/2026/5/")
        self.assertEqual(len(response.context["days_data"]), 31)

    def test_month_detail_soll_days_exclude_weekends_and_holidays(self):
        response = self.client.get("/timetracking/monat/2026/5/")
        self.assertGreater(response.context["soll_days_count"], 0)
        self.assertLessEqual(response.context["soll_days_count"], 22)
```

- [ ] **Schritt 2: `dashboard`-View komplett ersetzen**

Ersetze die `dashboard`-Funktion in `views.py`:

```python
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

    daily_equiv = active_job.weekly_target_hours / Decimal("5")
    week_data = []
    for day in week_days:
        entry = entries_this_week.get(day)
        holiday_name = get_holiday_name(day, bundesland)
        is_weekend = day.weekday() >= 5
        is_soll = not is_weekend and not holiday_name

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = daily_equiv
        else:
            ist = Decimal("0")

        pending = day == today and not entry and is_soll
        week_data.append({
            "day": day,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "ist": ist,
            "pending": pending,
        })

    from .utils import calculate_weekly_saldo, calculate_total_saldo
    week_saldo_data = calculate_weekly_saldo(active_job, bundesland)
    current_week = next((w for w in week_saldo_data if w["is_current"]), None)
    total_saldo = calculate_total_saldo(active_job, bundesland)

    first_of_month = today.replace(day=1)
    _, days_in_month = monthrange(today.year, today.month)
    last_of_month = today.replace(day=days_in_month)
    from .utils import get_soll_days_in_range
    month_soll_days = get_soll_days_in_range(first_of_month, last_of_month, bundesland)
    month_soll = active_job.weekly_target_hours / Decimal("5") * Decimal(str(len(month_soll_days)))

    entries_this_month = WorkEntry.objects.filter(
        job=active_job, date__year=today.year, date__month=today.month
    )
    month_ist = Decimal("0")
    for e in entries_this_month:
        if e.entry_type == "work":
            month_ist += Decimal(str(e.worked_hours or 0))
        else:
            month_ist += daily_equiv

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
        "month_soll_days": len(month_soll_days),
        "month_soll": month_soll,
        "month_ist": month_ist,
        "month_saldo": month_ist - month_soll,
        "prev_month": prev_month_first,
        "next_month": next_month_first,
    })
```

- [ ] **Schritt 3: `month_detail`-View anpassen**

Ersetze `month_detail` in `views.py`:

```python
@login_required
def month_detail(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    bundesland = profile.bundesland
    daily_equiv = active_job.weekly_target_hours / Decimal("5")

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
        is_soll = not is_weekend and not holiday_name
        soll = daily_equiv if is_soll else Decimal("0")

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = daily_equiv
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
```

- [ ] **Schritt 4: `dashboard.html` — Job-Switcher + Wochensaldo ergänzen**

Ersetze den kompletten Inhalt von `templates/timetracking/dashboard.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4">

    <!-- Job-Switcher -->
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div class="d-flex align-items-center gap-3">
            <h1 class="h3 mb-0">Arbeitszeit</h1>
            <div class="dropdown">
                <button class="btn btn-sm btn-outline-primary dropdown-toggle" type="button" data-bs-toggle="dropdown">
                    {{ active_job.name }}
                </button>
                <ul class="dropdown-menu">
                    {% for job in all_jobs %}
                    <li>
                        <form method="post" action="{% url 'timetracking:job_activate' job.pk %}">
                            {% csrf_token %}
                            <button type="submit" class="dropdown-item {% if job == active_job %}active{% endif %}">
                                {{ job.name }}
                            </button>
                        </form>
                    </li>
                    {% endfor %}
                    <li><hr class="dropdown-divider"></li>
                    <li><a class="dropdown-item" href="{% url 'timetracking:job_list' %}">Jobs verwalten</a></li>
                </ul>
            </div>
        </div>
        <a href="{% url 'timetracking:settings_view' %}" class="btn btn-sm btn-outline-secondary">Einstellungen</a>
    </div>

    <!-- Gesamtsaldo -->
    <div class="card mb-4 text-center">
        <div class="card-body py-4">
            {% if active_job.work_start_date %}
            <div class="text-muted mb-1">Gesamtsaldo seit {{ active_job.work_start_date|date:"d.m.Y" }} – {{ active_job.name }}</div>
            <div class="display-5 fw-bold {% if total_saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                {% if total_saldo >= 0 %}+{% endif %}{{ total_saldo|floatformat:2 }}h
            </div>
            {% else %}
            <div class="text-muted">Kein Startdatum gesetzt — <a href="{% url 'timetracking:job_list' %}">Job bearbeiten</a></div>
            {% endif %}
        </div>
    </div>

    <div class="row g-4">
        <!-- Wochenübersicht -->
        <div class="col-lg-7">
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0">Diese Woche</h5>
                    {% if current_week %}
                    <small class="text-muted">KW {{ current_week.iso_week }}: {{ current_week.ist|floatformat:1 }}h / {{ current_week.soll|floatformat:1 }}h
                        <span class="{% if current_week.saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                            ({% if current_week.saldo >= 0 %}+{% endif %}{{ current_week.saldo|floatformat:1 }}h)
                        </span>
                    </small>
                    {% endif %}
                </div>
                <div class="card-body p-0">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th class="ps-3">Tag</th>
                                <th class="text-end pe-3">Ist</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for d in week_data %}
                        <tr class="{% if d.is_weekend %}text-muted{% elif d.holiday_name %}table-info{% elif d.day == today %}table-warning{% endif %}">
                            <td class="ps-3">
                                {{ d.day|date:"D, d.m." }}
                                {% if d.holiday_name %}<br><small class="text-muted">{{ d.holiday_name }}</small>{% endif %}
                                {% if d.entry and not d.is_weekend and not d.holiday_name %}
                                <br><small class="text-muted">
                                    {{ d.entry.get_entry_type_display }}
                                    {% if d.entry.start_time %} {{ d.entry.start_time|time:"H:i" }}–{{ d.entry.end_time|time:"H:i" }}{% endif %}
                                </small>
                                {% endif %}
                            </td>
                            <td class="text-end pe-3">
                                {% if not d.is_weekend %}
                                    {% if d.pending %}–{% else %}{{ d.ist|floatformat:2 }}h{% endif %}
                                {% endif %}
                            </td>
                            <td class="text-end">
                                {% if not d.is_weekend and not d.holiday_name %}
                                    {% if d.entry %}
                                    <a href="{% url 'timetracking:entry_edit' d.entry.pk %}" class="btn btn-sm btn-outline-secondary py-0 px-1">&#9998;</a>
                                    <a href="{% url 'timetracking:entry_delete' d.entry.pk %}" class="btn btn-sm btn-outline-danger py-0 px-1">&#10005;</a>
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
                    <div class="d-flex gap-2">
                        <a href="{% url 'timetracking:month_detail' today.year today.month %}" class="btn btn-sm btn-outline-primary flex-grow-1">Monatsdetail</a>
                        <a href="{% url 'timetracking:report_view' today.year today.month %}" class="btn btn-sm btn-outline-secondary flex-grow-1">Bericht</a>
                    </div>
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

- [ ] **Schritt 5: Tests ausführen**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking -v 0 2>&1 | tail -5
```
Erwartete Ausgabe: `OK` (alle Tests grün)

- [ ] **Schritt 6: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/ templates/timetracking/ && git commit -m "feat: job switcher on dashboard, weekly saldo display"
```

---

## Task 10: Monatsbericht HTML View + Template

**Files:**
- Modify: `timetracking/views.py` (report_view vollständig implementieren)
- Modify: `templates/timetracking/report.html`
- Modify: `timetracking/tests.py` (ReportViewTest hinzufügen)

- [ ] **Schritt 1: Failing tests hinzufügen**

Füge am Ende von `tests.py` hinzu:

```python
class ReportViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="reportuser", password="pw123456")
        self.client.login(username="reportuser", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user,
            name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 5, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_report_view_loads(self):
        response = self.client.get("/timetracking/bericht/2026/5/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arbeitszeitnachweis")
        self.assertContains(response, "Hauptjob")

    def test_report_shows_week_summary(self):
        response = self.client.get("/timetracking/bericht/2026/5/")
        self.assertIn("week_rows", response.context)
        self.assertGreater(len(response.context["week_rows"]), 0)

    def test_report_shows_day_details(self):
        response = self.client.get("/timetracking/bericht/2026/5/")
        self.assertIn("days_data", response.context)
        self.assertEqual(len(response.context["days_data"]), 31)
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.ReportViewTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: `report_view` vollständig implementieren in `views.py`**

Ersetze den `report_view`-Stub:

```python
@login_required
def report_view(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    bundesland = profile.bundesland
    daily_equiv = active_job.weekly_target_hours / Decimal("5")

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
        is_soll = not is_weekend and not holiday_name
        soll = daily_equiv if is_soll else Decimal("0")
        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = daily_equiv
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

    from .utils import calculate_weekly_saldo
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
```

- [ ] **Schritt 4: `report.html` vollständig erstellen**

```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbeitszeitnachweis {{ active_job.name }} {{ month_name }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        @media print {
            .no-print { display: none !important; }
            body { font-size: 10pt; }
            .card { border: 1px solid #dee2e6 !important; }
        }
        body { background: white; }
    </style>
</head>
<body class="p-4">
    <div class="no-print mb-3 d-flex gap-2">
        <a href="{% url 'timetracking:dashboard' %}" class="btn btn-outline-secondary btn-sm">← Dashboard</a>
        <a href="{% url 'timetracking:report_pdf' year month %}" class="btn btn-primary btn-sm">PDF herunterladen</a>
        <form method="post" action="{% url 'timetracking:report_email' year month %}" class="d-inline">
            {% csrf_token %}
            <button type="submit" class="btn btn-outline-primary btn-sm">Per E-Mail senden</button>
        </form>
        <button onclick="window.print()" class="btn btn-outline-secondary btn-sm">Drucken</button>
    </div>

    <div class="mb-4">
        <h2 class="h4">Arbeitszeitnachweis</h2>
        <p class="mb-1"><strong>Job:</strong> {{ active_job.name }}</p>
        <p class="mb-1"><strong>Zeitraum:</strong> {{ month_name }}</p>
        <p class="mb-1"><strong>Wochensoll:</strong> {{ active_job.weekly_target_hours }}h</p>
        <p class="mb-0"><strong>Mitarbeiter:</strong> {{ profile.user.username }}</p>
    </div>

    <h5 class="mb-2">Wochenübersicht</h5>
    <table class="table table-bordered table-sm mb-4">
        <thead class="table-light">
            <tr>
                <th>KW</th>
                <th>Zeitraum</th>
                <th class="text-end">Soll</th>
                <th class="text-end">Ist</th>
                <th class="text-end">Saldo</th>
            </tr>
        </thead>
        <tbody>
        {% for w in week_rows %}
        <tr>
            <td>{{ w.iso_week }}</td>
            <td>{{ w.week_start|date:"d.m." }}–{{ w.week_end|date:"d.m.Y" }}</td>
            <td class="text-end">{{ w.soll|floatformat:2 }}h</td>
            <td class="text-end">{{ w.ist|floatformat:2 }}h</td>
            <td class="text-end fw-bold {% if w.saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                {% if w.saldo >= 0 %}+{% endif %}{{ w.saldo|floatformat:2 }}h
            </td>
        </tr>
        {% endfor %}
        </tbody>
        <tfoot class="table-light fw-bold">
            <tr>
                <td colspan="2">Gesamt</td>
                <td class="text-end">{{ month_soll|floatformat:2 }}h</td>
                <td class="text-end">{{ month_ist|floatformat:2 }}h</td>
                <td class="text-end {% if month_saldo >= 0 %}text-success{% else %}text-danger{% endif %}">
                    {% if month_saldo >= 0 %}+{% endif %}{{ month_saldo|floatformat:2 }}h
                </td>
            </tr>
        </tfoot>
    </table>

    <h5 class="mb-2">Tagesdetails</h5>
    <table class="table table-bordered table-sm">
        <thead class="table-light">
            <tr>
                <th>Datum</th>
                <th>Typ</th>
                <th class="text-end">Beginn</th>
                <th class="text-end">Ende</th>
                <th class="text-end">Pause</th>
                <th class="text-end">Stunden</th>
            </tr>
        </thead>
        <tbody>
        {% for d in days_data %}
        {% if not d.is_weekend %}
        <tr class="{% if d.holiday_name %}table-secondary{% endif %}">
            <td>{{ d.day|date:"D, d.m.Y" }}</td>
            <td>
                {% if d.holiday_name %}Feiertag ({{ d.holiday_name }})
                {% elif d.entry %}{{ d.entry.get_entry_type_display }}
                {% else %}–{% endif %}
            </td>
            <td class="text-end">{% if d.entry and d.entry.start_time %}{{ d.entry.start_time|time:"H:i" }}{% else %}–{% endif %}</td>
            <td class="text-end">{% if d.entry and d.entry.end_time %}{{ d.entry.end_time|time:"H:i" }}{% else %}–{% endif %}</td>
            <td class="text-end">{% if d.entry and d.entry.break_minutes %}{{ d.entry.break_minutes }}min{% else %}–{% endif %}</td>
            <td class="text-end">{% if d.ist %}{{ d.ist|floatformat:2 }}h{% else %}–{% endif %}</td>
        </tr>
        {% endif %}
        {% endfor %}
        </tbody>
    </table>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
```

- [ ] **Schritt 5: Tests ausführen — müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.ReportViewTest -v 2 2>&1 | tail -10
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 6: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/views.py timetracking/tests.py templates/timetracking/report.html && git commit -m "feat: monthly report HTML view and template"
```

---

## Task 11: PDF-Download + E-Mail

**Files:**
- Modify: `timetracking/views.py` (report_pdf, report_email vollständig)
- Modify: `wochi/settings.py` (E-Mail-Konfiguration)
- Modify: `timetracking/tests.py` (ReportPDFTest + ReportEmailTest)

- [ ] **Schritt 1: Failing tests hinzufügen**

Füge am Ende von `tests.py` hinzu:

```python
class ReportPDFTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pdfuser", password="pw123456", email="test@example.com")
        self.client.login(username="pdfuser", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"), work_start_date=date(2026, 5, 1)
        )
        profile.active_job = job
        profile.save()

    def test_pdf_download_returns_pdf(self):
        response = self.client.get("/timetracking/bericht/2026/5/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_email_redirects_after_send(self):
        response = self.client.post("/timetracking/bericht/2026/5/email/")
        self.assertRedirects(response, "/timetracking/bericht/2026/5/", fetch_redirect_response=False)
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.ReportPDFTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: E-Mail-Einstellungen zu `wochi/settings.py` hinzufügen**

Füge am Ende von `wochi/settings.py` ein:

```python
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@wochii.de")
```

- [ ] **Schritt 4: `report_pdf` implementieren**

Ersetze den `report_pdf`-Stub in `views.py`:

```python
@login_required
def report_pdf(request, year, month):
    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    active_job = profile.active_job
    bundesland = profile.bundesland
    daily_equiv = active_job.weekly_target_hours / Decimal("5")

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
        is_soll = not is_weekend and not holiday_name
        soll = daily_equiv if is_soll else Decimal("0")
        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = daily_equiv
        else:
            ist = Decimal("0")
        days_data.append({
            "day": d, "entry": entry, "holiday_name": holiday_name,
            "is_weekend": is_weekend, "soll": soll, "ist": ist, "diff": ist - soll,
        })

    from .utils import calculate_weekly_saldo
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
```

- [ ] **Schritt 5: `report_email` implementieren**

Ersetze den `report_email`-Stub in `views.py`:

```python
@login_required
def report_email(request, year, month):
    if request.method != "POST":
        return redirect("timetracking:report_view", year=year, month=month)

    profile = get_or_create_profile(request.user)
    if not profile.timetracking_enabled or not profile.active_job:
        return redirect("timetracking:settings_view")

    if not request.user.email:
        messages.error(request, "Kein E-Mail-Adresse im Profil hinterlegt.")
        return redirect("timetracking:report_view", year=year, month=month)

    active_job = profile.active_job
    bundesland = profile.bundesland
    daily_equiv = active_job.weekly_target_hours / Decimal("5")

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
        is_soll = not is_weekend and not holiday_name
        soll = daily_equiv if is_soll else Decimal("0")
        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = daily_equiv
        else:
            ist = Decimal("0")
        days_data.append({
            "day": d, "entry": entry, "holiday_name": holiday_name,
            "is_weekend": is_weekend, "soll": soll, "ist": ist, "diff": ist - soll,
        })

    from .utils import calculate_weekly_saldo
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
```

- [ ] **Schritt 6: `report.html` — CDN-Links für PDF-Modus anpassen**

In `report.html`, ersetze den Bootstrap-CSS-Link:
```html
    {% if not pdf_mode %}
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    {% endif %}
```
Und füge inline-CSS für den PDF-Modus ein (nach dem `<style>`-Block):
```html
    {% if pdf_mode %}
    <style>
        .no-print { display: none !important; }
        body { font-family: sans-serif; font-size: 10pt; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border: 1px solid #ccc; padding: 4px 8px; }
        th { background: #f0f0f0; }
        .text-end { text-align: right; }
        .text-success { color: green; }
        .text-danger { color: red; }
        .table-secondary { background: #f8f8f8; }
        .fw-bold { font-weight: bold; }
    </style>
    {% endif %}
```

- [ ] **Schritt 7: Tests ausführen — müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking.tests.ReportPDFTest -v 2 2>&1 | tail -10
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 8: Alle Tests**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test timetracking -v 0 2>&1 | tail -5
```
Erwartete Ausgabe: `OK`

- [ ] **Schritt 9: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/ wochi/settings.py templates/timetracking/report.html && git commit -m "feat: PDF download and email for monthly report"
```

---

## Abschluss

- [ ] **Alle Tests laufen durch**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test
```

- [ ] **Django-Check**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py check
```

- [ ] **Alte Felder aus UserProfile entfernen** (optionaler Cleanup-Commit nach erfolgreichem Test)

Entferne `daily_target_hours` und `work_start_date` aus `timetracking/models.py` → `UserProfile`, dann:

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py makemigrations timetracking && python manage.py migrate
```

- [ ] **Push**

```bash
cd /home/stefan/Projekte/Wochi && git push origin main
```
