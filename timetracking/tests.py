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
        # Week of May 4-8: 40h soll, worked 9h/day * 5 = 45h
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
        today = date.today()
        self.job.work_start_date = get_week_start(today)
        self.job.save()
        weeks = calculate_weekly_saldo(self.job, "BY")
        if weeks:
            current = next((w for w in weeks if w["is_current"]), None)
            if current:
                self.assertEqual(current["saldo"], Decimal("0.00"))


class SettingsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="settingsuser", password="pw123456")
        self.client.login(username="settingsuser", password="pw123456")

    def test_settings_page_loads(self):
        response = self.client.get("/timetracking/einstellungen/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bundesland")

    def test_settings_requires_login(self):
        self.client.logout()
        response = self.client.get("/timetracking/einstellungen/")
        self.assertRedirects(response, "/accounts/login/?next=/timetracking/einstellungen/")


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


class WeekendHolidayFormValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="formtest", password="pw123456")
        profile = self.user.userprofile
        profile.bundesland = "BY"
        profile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )

    def _form(self, data):
        from timetracking.forms import WorkEntryForm
        return WorkEntryForm(data=data, user=self.user, bundesland="BY")

    def test_work_entry_on_saturday_is_valid(self):
        # 2026-05-30 ist ein Samstag
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-30",
            "entry_type": "work",
            "start_time": "10:00",
            "end_time": "14:00",
            "break_minutes": "0",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_work_entry_on_bavarian_holiday_is_valid(self):
        # 2026-05-01 (Tag der Arbeit) ist Feiertag in BY
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-01",
            "entry_type": "work",
            "start_time": "09:00",
            "end_time": "13:00",
            "break_minutes": "0",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_urlaub_on_saturday_is_rejected(self):
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-30",
            "entry_type": "urlaub",
            "break_minutes": "0",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("entry_type", form.errors)

    def test_krankheit_on_holiday_is_rejected(self):
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-01",
            "entry_type": "krankheit",
            "break_minutes": "0",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("entry_type", form.errors)

    def test_homeoffice_on_sunday_is_rejected(self):
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-31",
            "entry_type": "homeoffice",
            "break_minutes": "0",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("entry_type", form.errors)

    def test_urlaub_on_normal_weekday_still_valid(self):
        # 2026-05-04 ist ein Montag, kein Feiertag in BY
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-04",
            "entry_type": "urlaub",
            "break_minutes": "0",
        })
        self.assertTrue(form.is_valid(), form.errors)


class WeekendHolidaySaldoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="saldotest", password="pw123456")
        profile = self.user.userprofile
        profile.bundesland = "BY"
        profile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 5, 4),  # Montag der KW 19
        )

    def test_saturday_work_increases_saldo(self):
        from timetracking.models import WorkEntry
        from timetracking.utils import calculate_total_saldo
        from datetime import time
        # Mo-Fr (4.-8.5.) jeweils 8h = 40h Soll/Ist = 0 Saldo
        for day_offset in range(5):
            WorkEntry.objects.create(
                user=self.user, job=self.job,
                date=date(2026, 5, 4 + day_offset),
                entry_type="work",
                start_time=time(8, 0), end_time=time(16, 0), break_minutes=0,
            )
        # Sa (9.5.) zusätzlich 4h Arbeit
        WorkEntry.objects.create(
            user=self.user, job=self.job,
            date=date(2026, 5, 9),
            entry_type="work",
            start_time=time(10, 0), end_time=time(14, 0), break_minutes=0,
        )
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("4.00"))

    def test_holiday_work_increases_saldo(self):
        from timetracking.models import WorkEntry
        from timetracking.utils import calculate_total_saldo
        from datetime import time
        # 2026-05-01 ist Feiertag in BY (Tag der Arbeit). Job-Startdatum vorziehen:
        self.job.work_start_date = date(2026, 4, 27)
        self.job.save()
        # KW 18 (27.4.-3.5.): Mo-Do (27.-30.4.) je 8h, Fr (1.5.) ist Feiertag
        # → Soll = 4 Tage × 8h = 32h
        for day_offset in range(4):
            WorkEntry.objects.create(
                user=self.user, job=self.job,
                date=date(2026, 4, 27 + day_offset),
                entry_type="work",
                start_time=time(8, 0), end_time=time(16, 0), break_minutes=0,
            )
        # Feiertag 1.5.: 5h Arbeit → +5h Saldo
        WorkEntry.objects.create(
            user=self.user, job=self.job,
            date=date(2026, 5, 1),
            entry_type="work",
            start_time=time(9, 0), end_time=time(14, 0), break_minutes=0,
        )
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 4))
        self.assertEqual(saldo, Decimal("5.00"))
