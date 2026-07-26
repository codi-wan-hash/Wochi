from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from datetime import date
from decimal import Decimal

User = get_user_model()


def make_job(user, name="Hauptjob", daily=Decimal("8.00"), work_start_date=None, weekend=Decimal("0")):
    """Test helper: creates a Job with Mo-Fr = daily, Sa/So = weekend."""
    from timetracking.models import Job
    return Job.objects.create(
        user=user,
        name=name,
        work_start_date=work_start_date or date(2026, 1, 1),
        monday_hours=daily,
        tuesday_hours=daily,
        wednesday_hours=daily,
        thursday_hours=daily,
        friday_hours=daily,
        saturday_hours=weekend,
        sunday_hours=weekend,
    )


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
        user = User.objects.create_user(username="jobtest", password="pw123456")
        job = make_job(user, daily=Decimal("8.00"), work_start_date=date(2026, 1, 1))
        self.assertEqual(str(job), "Hauptjob (jobtest)")
        self.assertEqual(job.weekly_target_hours, Decimal("40.00"))

    def test_job_unique_name_per_user(self):
        from django.db import IntegrityError
        user = User.objects.create_user(username="duptest", password="pw123456")
        make_job(user)
        with self.assertRaises(IntegrityError):
            make_job(user, daily=Decimal("4.00"))


class JobWeekdayHoursTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="weekday", password="pw123456")
        self.user.userprofile.bundesland = "BY"
        self.user.userprofile.save()

    def test_weekly_target_hours_property_is_sum(self):
        from timetracking.models import Job
        job = Job.objects.create(
            user=self.user, name="Job1", work_start_date=date(2026, 1, 1),
            monday_hours=Decimal("9"), tuesday_hours=Decimal("9"),
            wednesday_hours=Decimal("9"), thursday_hours=Decimal("9"),
            friday_hours=Decimal("4"), saturday_hours=Decimal("0"), sunday_hours=Decimal("0"),
        )
        self.assertEqual(job.weekly_target_hours, Decimal("40"))

    def test_hours_for_weekday_index(self):
        from timetracking.models import Job
        job = Job.objects.create(
            user=self.user, name="Job1", work_start_date=date(2026, 1, 1),
            monday_hours=Decimal("8"), tuesday_hours=Decimal("7"),
            wednesday_hours=Decimal("6"), thursday_hours=Decimal("5"),
            friday_hours=Decimal("4"), saturday_hours=Decimal("3"), sunday_hours=Decimal("2"),
        )
        self.assertEqual(job.hours_for_weekday(0), Decimal("8"))
        self.assertEqual(job.hours_for_weekday(4), Decimal("4"))
        self.assertEqual(job.hours_for_weekday(6), Decimal("2"))

    def test_get_daily_target_holiday_zeros_out(self):
        from timetracking.utils import get_daily_target
        job = make_job(self.user, work_start_date=date(2026, 5, 1))
        # 2026-05-01 = Tag der Arbeit (DE), Friday
        self.assertEqual(get_daily_target(job, date(2026, 5, 1), "BY"), Decimal("0"))
        # 2026-05-04 = regular Monday
        self.assertEqual(get_daily_target(job, date(2026, 5, 4), "BY"), Decimal("8.00"))

    def test_get_daily_target_weekend_when_configured(self):
        from timetracking.models import Job
        from timetracking.utils import get_daily_target
        job = Job.objects.create(
            user=self.user, name="Schicht", work_start_date=date(2026, 1, 1),
            monday_hours=Decimal("8"), tuesday_hours=Decimal("8"),
            wednesday_hours=Decimal("8"), thursday_hours=Decimal("8"),
            friday_hours=Decimal("0"), saturday_hours=Decimal("4"), sunday_hours=Decimal("0"),
        )
        self.assertEqual(get_daily_target(job, date(2026, 5, 2), "BY"), Decimal("4"))  # Sa
        self.assertEqual(get_daily_target(job, date(2026, 5, 8), "BY"), Decimal("0"))  # Fr


class WorkEntryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="worker", password="pw123456")
        self.job = make_job(self.user)

    def test_worked_hours_calculation(self):
        from timetracking.models import WorkEntry
        from datetime import time
        entry = WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="work",
            start_time=time(8, 0), end_time=time(16, 30), break_minutes=30,
        )
        self.assertEqual(entry.worked_hours, 8.0)

    def test_worked_hours_none_for_absence(self):
        from timetracking.models import WorkEntry
        entry = WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="urlaub",
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
        self.job = make_job(self.user, work_start_date=date(2026, 5, 4))

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
        for day_offset in range(5):
            d = date(2026, 5, 4 + day_offset)
            WorkEntry.objects.create(
                user=self.user, job=self.job, date=d, entry_type="work",
                start_time=time(8, 0), end_time=time(17, 0), break_minutes=0,
            )
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("5.00"))

    def test_weekly_saldo_absence_counts_as_daily_equiv(self):
        from timetracking.utils import calculate_total_saldo
        from timetracking.models import WorkEntry
        for day_offset in range(5):
            d = date(2026, 5, 4 + day_offset)
            WorkEntry.objects.create(user=self.user, job=self.job, date=d, entry_type="urlaub")
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("0.00"))

    def test_current_week_no_entries_no_deficit(self):
        from timetracking.utils import calculate_weekly_saldo, get_week_start
        today = date.today()
        self.job.work_start_date = get_week_start(today)
        self.job.save()
        weeks = calculate_weekly_saldo(self.job, "BY")
        if weeks:
            current = next((w for w in weeks if w["is_current"]), None)
            if current:
                self.assertEqual(current["saldo"], Decimal("0.00"))


class PerDayTargetSaldoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="customday", password="pw123456")
        self.user.userprofile.bundesland = "BY"
        self.user.userprofile.save()

    def test_per_day_target_friday_short(self):
        """Mo-Do 9h, Fr 4h = 40h Woche. Wenn jeden Tag genau Soll gearbeitet, Saldo 0."""
        from timetracking.models import Job, WorkEntry
        from timetracking.utils import calculate_total_saldo
        from datetime import time
        job = Job.objects.create(
            user=self.user, name="ShortFriday", work_start_date=date(2026, 5, 4),
            monday_hours=Decimal("9"), tuesday_hours=Decimal("9"),
            wednesday_hours=Decimal("9"), thursday_hours=Decimal("9"),
            friday_hours=Decimal("4"), saturday_hours=Decimal("0"), sunday_hours=Decimal("0"),
        )
        # Mo-Do je 9h
        for day_offset in range(4):
            WorkEntry.objects.create(
                user=self.user, job=job, date=date(2026, 5, 4 + day_offset),
                entry_type="work", start_time=time(8, 0), end_time=time(17, 0), break_minutes=0,
            )
        # Fr 4h
        WorkEntry.objects.create(
            user=self.user, job=job, date=date(2026, 5, 8),
            entry_type="work", start_time=time(8, 0), end_time=time(12, 0), break_minutes=0,
        )
        saldo = calculate_total_saldo(job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("0.00"))

    def test_weekend_target_counts_as_workday(self):
        """Sa 4h konfiguriert, kein Eintrag → Saldo -4h für Wochenende."""
        from timetracking.models import Job, WorkEntry
        from timetracking.utils import calculate_total_saldo
        from datetime import time
        job = Job.objects.create(
            user=self.user, name="WithSat", work_start_date=date(2026, 5, 4),
            monday_hours=Decimal("8"), tuesday_hours=Decimal("8"),
            wednesday_hours=Decimal("8"), thursday_hours=Decimal("8"),
            friday_hours=Decimal("8"), saturday_hours=Decimal("4"), sunday_hours=Decimal("0"),
        )
        # Mo-Fr voll arbeiten (40h)
        for day_offset in range(5):
            WorkEntry.objects.create(
                user=self.user, job=job, date=date(2026, 5, 4 + day_offset),
                entry_type="work", start_time=time(8, 0), end_time=time(16, 0),
                break_minutes=0,
            )
        # Sa nicht arbeiten → Wochensoll 44h, Ist 40h → -4h
        saldo = calculate_total_saldo(job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("-4.00"))

    def test_holiday_zeros_out_configured_workday(self):
        """Feiertag an konfiguriertem Werktag → Soll = 0."""
        from timetracking.utils import get_daily_target
        # Christi Himmelfahrt 2026 = Donnerstag 14. Mai (BY)
        job = make_job(self.user, work_start_date=date(2026, 5, 1))
        self.assertEqual(get_daily_target(job, date(2026, 5, 14), "BY"), Decimal("0"))

    def test_absence_uses_per_day_target(self):
        """Urlaub am Tag mit 6h Soll → ist = 6h, nicht durchschnittliches Soll."""
        from timetracking.models import Job, WorkEntry
        from timetracking.utils import calculate_weekly_saldo
        job = Job.objects.create(
            user=self.user, name="MixedHours", work_start_date=date(2026, 5, 4),
            monday_hours=Decimal("10"), tuesday_hours=Decimal("10"),
            wednesday_hours=Decimal("10"), thursday_hours=Decimal("10"),
            friday_hours=Decimal("6"), saturday_hours=Decimal("0"), sunday_hours=Decimal("0"),
        )
        # Urlaub am Freitag 2026-05-08
        WorkEntry.objects.create(
            user=self.user, job=job, date=date(2026, 5, 8), entry_type="urlaub",
        )
        weeks = calculate_weekly_saldo(job, "BY", as_of=date(2026, 5, 11))
        target_week = next(w for w in weeks if w["week_start"] == date(2026, 5, 4))
        # Soll = 10+10+10+10+6 = 46h; ist = 6h (Urlaub mit Fr-Soll)
        self.assertEqual(target_week["soll"], Decimal("46"))
        self.assertEqual(target_week["ist"], Decimal("6"))


class HolidayCreditBasisTest(TestCase):
    """Holiday credit basis: per_day (default) vs weekly_average."""

    def setUp(self):
        self.user = User.objects.create_user(username="holcredit", password="pw123456")
        self.user.userprofile.bundesland = "BY"
        self.user.userprofile.save()

    def _make_unequal_job(self, basis="per_day", work_start_date=None):
        """Mo–Do = 8.5h, Fr = 6h → 40h Woche, Avg = 8h."""
        from timetracking.models import Job
        return Job.objects.create(
            user=self.user, name="Vertrag",
            work_start_date=work_start_date or date(2026, 5, 1),
            monday_hours=Decimal("8.5"), tuesday_hours=Decimal("8.5"),
            wednesday_hours=Decimal("8.5"), thursday_hours=Decimal("8.5"),
            friday_hours=Decimal("6"), saturday_hours=Decimal("0"), sunday_hours=Decimal("0"),
            holiday_credit_basis=basis,
        )

    def test_holiday_credit_per_day_default(self):
        from timetracking.utils import get_daily_target
        job = self._make_unequal_job(basis="per_day")
        # 2026-05-25 = Pfingstmontag (BY), config Mo = 8.5
        self.assertEqual(get_daily_target(job, date(2026, 5, 25), "BY"), Decimal("0"))
        # 2026-05-01 = Tag der Arbeit, Friday, config Fr = 6
        self.assertEqual(get_daily_target(job, date(2026, 5, 1), "BY"), Decimal("0"))

    def test_holiday_credit_weekly_average_heavy_day(self):
        from timetracking.utils import get_daily_target, calculate_weekly_saldo
        job = self._make_unequal_job(basis="weekly_average")
        # 2026-05-25 Pfingstmontag (BY), Mo config 8.5, avg 8 → 8.5 − 8 = 0.5
        self.assertEqual(get_daily_target(job, date(2026, 5, 25), "BY"), Decimal("0.5"))
        # Wochensumme der Pfingst-Woche (Mo 25.5. – So 31.5.2026): kein weiterer Feiertag.
        # Soll: Mo 0.5 + Di+Mi+Do je 8.5 + Fr 6 + Sa+So 0 = 0.5+25.5+6 = 32
        weeks = calculate_weekly_saldo(job, "BY", as_of=date(2026, 6, 1))
        target_week = next(w for w in weeks if w["week_start"] == date(2026, 5, 25))
        self.assertEqual(target_week["soll"], Decimal("32.0"))

    def test_holiday_credit_weekly_average_light_day(self):
        from timetracking.utils import get_daily_target, calculate_weekly_saldo
        # work_start_date vor April 27, damit volle Woche zählt
        job = self._make_unequal_job(basis="weekly_average", work_start_date=date(2026, 4, 1))
        # 2026-05-01 Tag der Arbeit, Fr config 6, avg 8 → 6 − 8 = −2
        self.assertEqual(get_daily_target(job, date(2026, 5, 1), "BY"), Decimal("-2"))
        # Wochensumme der Woche 27.4.–3.5.2026:
        # Mo–Do je 8.5 (kein Feiertag) = 34, Fr (Feiertag) = −2, Sa+So 0 → 32
        weeks = calculate_weekly_saldo(job, "BY", as_of=date(2026, 5, 4))
        target_week = next(w for w in weeks if w["week_start"] == date(2026, 4, 27))
        self.assertEqual(target_week["soll"], Decimal("32.0"))

    def test_holiday_credit_weekly_average_non_workday_config(self):
        """Mode weekly_average aber Wochentag mit config=0 → kein Effekt."""
        from timetracking.models import Job
        from timetracking.utils import get_daily_target
        # User arbeitet nicht montags (config Mo = 0)
        job = Job.objects.create(
            user=self.user, name="OhneMo", work_start_date=date(2026, 5, 1),
            monday_hours=Decimal("0"), tuesday_hours=Decimal("10"),
            wednesday_hours=Decimal("10"), thursday_hours=Decimal("10"),
            friday_hours=Decimal("10"), saturday_hours=Decimal("0"), sunday_hours=Decimal("0"),
            holiday_credit_basis="weekly_average",
        )
        # 2026-05-25 Pfingstmontag, config Mo = 0 → keine Entlastung, returns 0
        self.assertEqual(get_daily_target(job, date(2026, 5, 25), "BY"), Decimal("0"))

    def test_holiday_before_work_start_date_returns_zero(self):
        """Pre-work_start_date Feiertag darf nicht im Monatssaldo zählen."""
        from timetracking.models import Job
        from timetracking.utils import get_daily_target
        job = Job.objects.create(
            user=self.user, name="StartMidMonth", work_start_date=date(2026, 5, 4),
            monday_hours=Decimal("8.5"), tuesday_hours=Decimal("8.5"),
            wednesday_hours=Decimal("8.5"), thursday_hours=Decimal("8.5"),
            friday_hours=Decimal("6"), saturday_hours=Decimal("0"), sunday_hours=Decimal("0"),
            holiday_credit_basis="weekly_average",
        )
        # 2026-05-01 Tag der Arbeit (Fr Feiertag), aber vor work_start_date → 0
        self.assertEqual(get_daily_target(job, date(2026, 5, 1), "BY"), Decimal("0"))
        # Regulärer Mo 2026-05-04 (work_start) → config 8.5
        self.assertEqual(get_daily_target(job, date(2026, 5, 4), "BY"), Decimal("8.5"))

    def test_holiday_credit_basis_form_choice_saved(self):
        from django.contrib.auth import get_user_model
        from timetracking.models import Job
        U = get_user_model()
        u = U.objects.create_user(username="formuser", password="pw123456")
        profile = u.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        client = Client()
        client.login(username="formuser", password="pw123456")
        response = client.post("/timetracking/jobs/neu/", {
            "name": "Job1",
            "work_start_date": "2026-01-01",
            "monday_hours": "8", "tuesday_hours": "8", "wednesday_hours": "8",
            "thursday_hours": "8", "friday_hours": "8",
            "saturday_hours": "0", "sunday_hours": "0",
            "holiday_credit_basis": "weekly_average",
        })
        self.assertIn(response.status_code, (200, 302))
        job = Job.objects.get(user=u, name="Job1")
        self.assertEqual(job.holiday_credit_basis, "weekly_average")


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
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user)
        profile.active_job = self.job
        profile.save()

    def test_entry_create_get(self):
        response = self.client.get("/timetracking/eintrag/neu/")
        self.assertEqual(response.status_code, 200)

    def test_entry_create_post_work(self):
        response = self.client.post("/timetracking/eintrag/neu/", {
            "job": self.job.pk, "date": "2026-05-04", "entry_type": "work",
            "start_time": "08:00", "end_time": "16:30", "break_minutes": "30",
        })
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        from timetracking.models import WorkEntry
        self.assertEqual(WorkEntry.objects.filter(user=self.user).count(), 1)

    def test_entry_create_post_absence(self):
        response = self.client.post("/timetracking/eintrag/neu/", {
            "job": self.job.pk, "date": "2026-05-04", "entry_type": "urlaub", "break_minutes": "0",
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
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user)
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
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user)
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
        self.job = make_job(self.user)
        profile.active_job = self.job
        profile.save()

    def test_job_list_loads(self):
        response = self.client.get("/timetracking/jobs/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hauptjob")

    def test_job_create(self):
        response = self.client.post("/timetracking/jobs/neu/", {
            "name": "Nebenjob",
            "work_start_date": "2026-03-01",
            "monday_hours": "4", "tuesday_hours": "4", "wednesday_hours": "4",
            "thursday_hours": "4", "friday_hours": "4",
            "saturday_hours": "0", "sunday_hours": "0",
            "holiday_credit_basis": "per_day",
        })
        self.assertRedirects(response, "/timetracking/jobs/", fetch_redirect_response=False)
        from timetracking.models import Job
        self.assertEqual(Job.objects.filter(user=self.user).count(), 2)

    def test_job_activate(self):
        job2 = make_job(self.user, name="Nebenjob", daily=Decimal("4"), work_start_date=date(2026, 3, 1))
        response = self.client.post(f"/timetracking/jobs/{job2.pk}/aktivieren/")
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.userprofile.active_job, job2)

    def test_job_delete_blocked_with_entries(self):
        from timetracking.models import WorkEntry, Job
        WorkEntry.objects.create(user=self.user, job=self.job, date=date(2026, 5, 4), entry_type="urlaub")
        response = self.client.post(f"/timetracking/jobs/{self.job.pk}/loeschen/")
        self.assertEqual(Job.objects.filter(user=self.user).count(), 1)

    def test_job_delete_allowed_without_entries(self):
        from timetracking.models import Job
        job2 = make_job(self.user, name="Leerjob", daily=Decimal("2"), work_start_date=date(2026, 5, 1))
        response = self.client.post(f"/timetracking/jobs/{job2.pk}/loeschen/")
        self.assertRedirects(response, "/timetracking/jobs/", fetch_redirect_response=False)
        self.assertEqual(Job.objects.filter(user=self.user, name="Leerjob").count(), 0)


class ReportViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="reportuser", password="pw123456")
        self.client.login(username="reportuser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user, work_start_date=date(2026, 5, 1))
        profile.active_job = self.job
        profile.save()

    MAY = "?von=2026-05-01&bis=2026-05-31"

    def test_report_view_loads(self):
        response = self.client.get("/timetracking/bericht/" + self.MAY)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arbeitszeitnachweis")
        self.assertContains(response, "Hauptjob")

    def test_report_shows_week_summary(self):
        response = self.client.get("/timetracking/bericht/" + self.MAY)
        self.assertIn("week_rows", response.context)
        self.assertGreater(len(response.context["week_rows"]), 0)

    def test_report_shows_day_details(self):
        response = self.client.get("/timetracking/bericht/" + self.MAY)
        self.assertIn("days_data", response.context)
        self.assertEqual(len(response.context["days_data"]), 31)

    def test_report_without_params_uses_current_month(self):
        from timetracking.periods import month_bounds, today_local
        today = today_local()
        first, last = month_bounds(today.year, today.month)
        response = self.client.get("/timetracking/bericht/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start"], first)
        self.assertEqual(response.context["end"], last)

    def test_old_month_url_redirects_to_range(self):
        response = self.client.get("/timetracking/bericht/2026/5/")
        self.assertRedirects(
            response,
            "/timetracking/bericht/" + self.MAY,
            fetch_redirect_response=False,
        )

    def test_end_before_start_is_rejected(self):
        response = self.client.get("/timetracking/bericht/?von=2026-05-31&bis=2026-05-01")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertIsNone(response.context.get("days_data"))

    def test_range_longer_than_max_is_rejected(self):
        response = self.client.get("/timetracking/bericht/?von=2020-01-01&bis=2026-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_week_sums_match_day_sums(self):
        """Der eigentliche Regressionstest: früher kamen die Monatssummen aus
        ganzen überlappenden Wochen und passten nicht zur Tagestabelle."""
        response = self.client.get("/timetracking/bericht/" + self.MAY)
        ctx = response.context
        week_soll = sum(w["soll"] for w in ctx["week_rows"])
        week_ist = sum(w["ist"] for w in ctx["week_rows"])
        day_soll = sum(d["soll_counted"] for d in ctx["days_data"])
        day_ist = sum(d["ist"] for d in ctx["days_data"])
        self.assertEqual(week_soll, day_soll)
        self.assertEqual(week_ist, day_ist)
        self.assertEqual(ctx["range_soll"], day_soll)
        self.assertEqual(ctx["range_ist"], day_ist)

    def test_saldo_before_plus_range_equals_saldo_after(self):
        response = self.client.get("/timetracking/bericht/" + self.MAY)
        ctx = response.context
        self.assertEqual(ctx["saldo_before"] + ctx["range_saldo"], ctx["saldo_after"])

    def test_future_month_has_no_soll(self):
        """Zukünftige Tage ohne Eintrag dürfen kein Minus erzeugen."""
        from timetracking.periods import add_months, month_bounds, today_local
        future = add_months(today_local(), 6)
        first, last = month_bounds(future.year, future.month)
        response = self.client.get(
            f"/timetracking/bericht/?von={first:%Y-%m-%d}&bis={last:%Y-%m-%d}"
        )
        self.assertEqual(response.context["range_soll"], Decimal("0"))
        self.assertEqual(response.context["range_saldo"], Decimal("0"))


class ReportPDFTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pdfuser", password="pw123456", email="test@example.com")
        self.client.login(username="pdfuser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        job = make_job(self.user, work_start_date=date(2026, 5, 1))
        profile.active_job = job
        profile.save()

    MAY = "?von=2026-05-01&bis=2026-05-31"

    def test_pdf_download_returns_pdf(self):
        response = self.client.get("/timetracking/bericht/pdf/" + self.MAY)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_pdf_filename_contains_range(self):
        response = self.client.get("/timetracking/bericht/pdf/" + self.MAY)
        self.assertIn("2026-05-01_bis_2026-05-31.pdf", response["Content-Disposition"])

    def test_email_redirects_after_send(self):
        response = self.client.post("/timetracking/bericht/email/" + self.MAY)
        self.assertRedirects(
            response,
            "/timetracking/bericht/" + self.MAY,
            fetch_redirect_response=False,
        )


class WeekendHolidayFormValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="formtest", password="pw123456")
        profile = self.user.userprofile
        profile.bundesland = "BY"
        profile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            monday_hours=Decimal("8.00"), tuesday_hours=Decimal("8.00"),
            wednesday_hours=Decimal("8.00"), thursday_hours=Decimal("8.00"),
            friday_hours=Decimal("8.00"),
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
            monday_hours=Decimal("8.00"), tuesday_hours=Decimal("8.00"),
            wednesday_hours=Decimal("8.00"), thursday_hours=Decimal("8.00"),
            friday_hours=Decimal("8.00"),
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


class DashboardWeekendEntryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="dashweekend", password="pw123456")
        self.client.login(username="dashweekend", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            monday_hours=Decimal("8.00"), tuesday_hours=Decimal("8.00"),
            wednesday_hours=Decimal("8.00"), thursday_hours=Decimal("8.00"),
            friday_hours=Decimal("8.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_weekend_entry_appears_with_ist_and_diff(self):
        from timetracking.models import WorkEntry
        from datetime import time, timedelta
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        saturday = monday + timedelta(days=5)
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=saturday,
            entry_type="work",
            start_time=time(10, 0), end_time=time(13, 0), break_minutes=0,
        )
        response = self.client.get("/timetracking/")
        week_data = response.context["week_data"]
        sat_row = next(d for d in week_data if d["day"] == saturday)
        self.assertEqual(sat_row["entry"].pk, WorkEntry.objects.first().pk)
        self.assertEqual(sat_row["ist"], Decimal("3.00"))
        self.assertEqual(sat_row["soll"], Decimal("0"))
        self.assertEqual(sat_row["diff"], Decimal("3.00"))
        self.assertFalse(sat_row["no_value"])


class MonthDetailWeekendEntryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="monthweekend", password="pw123456")
        self.client.login(username="monthweekend", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            monday_hours=Decimal("8.00"), tuesday_hours=Decimal("8.00"),
            wednesday_hours=Decimal("8.00"), thursday_hours=Decimal("8.00"),
            friday_hours=Decimal("8.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_weekend_entry_visible_in_month_detail(self):
        from timetracking.models import WorkEntry
        from datetime import time
        # 2026-05-09 ist ein Samstag
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 9),
            entry_type="work",
            start_time=time(10, 0), end_time=time(14, 0), break_minutes=0,
        )
        response = self.client.get("/timetracking/monat/2026/5/")
        content = response.content.decode("utf-8")
        # Die Stunden müssen in der gerenderten Tabelle erscheinen
        # (Django L10N rendert mit deutschem Dezimalkomma → "4,00h")
        self.assertIn("4,00h", content)
        # Es muss Bearbeiten-Link zum Eintrag geben
        pk = WorkEntry.objects.first().pk
        self.assertIn(f"/timetracking/eintrag/{pk}/bearbeiten/", content)


class ReportWeekendEntryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="reportweekend", password="pw123456")
        self.client.login(username="reportweekend", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            monday_hours=Decimal("8.00"), tuesday_hours=Decimal("8.00"),
            wednesday_hours=Decimal("8.00"), thursday_hours=Decimal("8.00"),
            friday_hours=Decimal("8.00"),
            work_start_date=date(2026, 5, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_saturday_entry_appears_in_report(self):
        from timetracking.models import WorkEntry
        from datetime import time
        # 2026-05-09 = Samstag
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 9),
            entry_type="work",
            start_time=time(10, 0), end_time=time(13, 30), break_minutes=0,
        )
        response = self.client.get("/timetracking/bericht/?von=2026-05-01&bis=2026-05-31")
        content = response.content.decode("utf-8")
        # 3,50h sollte in der Bericht-Tabelle erscheinen (de-Locale → Komma)
        self.assertIn("3,50h", content)
        # Datum 09.05.2026 sollte als Zeile vorhanden sein
        self.assertIn("09.05.2026", content)


class PeriodsTest(TestCase):
    """Die gemeinsame Zeitraum-Logik aus timetracking/periods.py."""

    def setUp(self):
        self.user = User.objects.create_user(username="periods", password="pw123456")
        self.job = make_job(self.user, work_start_date=date(2026, 1, 1))

    def test_day_rows_cover_range_inclusive(self):
        from timetracking.periods import build_day_rows
        rows = build_day_rows(self.job, "BY", date(2026, 3, 1), date(2026, 3, 31), date(2026, 7, 26))
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[0]["day"], date(2026, 3, 1))
        self.assertEqual(rows[-1]["day"], date(2026, 3, 31))

    def test_day_rows_across_year_boundary(self):
        from timetracking.periods import build_day_rows
        rows = build_day_rows(self.job, "BY", date(2026, 12, 28), date(2027, 1, 3), date(2026, 7, 26))
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[-1]["day"], date(2027, 1, 3))

    def test_reversed_range_is_empty(self):
        from timetracking.periods import build_day_rows
        rows = build_day_rows(self.job, "BY", date(2026, 3, 31), date(2026, 3, 1), date(2026, 7, 26))
        self.assertEqual(rows, [])

    def test_future_workday_without_entry_is_pending(self):
        from timetracking.periods import build_day_rows
        today = date(2026, 3, 10)  # Dienstag
        rows = build_day_rows(self.job, "BY", date(2026, 3, 9), date(2026, 3, 13), today)
        by_day = {r["day"]: r for r in rows}
        # Montag liegt in der Vergangenheit -> zählt als Fehlzeit
        self.assertFalse(by_day[date(2026, 3, 9)]["pending"])
        self.assertEqual(by_day[date(2026, 3, 9)]["soll_counted"], Decimal("8.00"))
        # Heute und später ohne Eintrag -> pending, kein Soll, keine Differenz
        for d in (date(2026, 3, 10), date(2026, 3, 11)):
            self.assertTrue(by_day[d]["pending"])
            self.assertEqual(by_day[d]["soll_counted"], Decimal("0"))
            self.assertEqual(by_day[d]["diff"], Decimal("0"))
            # Die Soll-Spalte zeigt den Wert trotzdem an
            self.assertEqual(by_day[d]["soll"], Decimal("8.00"))

    def test_past_day_with_entry_is_not_pending(self):
        from datetime import time
        from timetracking.models import WorkEntry
        from timetracking.periods import build_day_rows
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 3, 11), entry_type="work",
            start_time=time(9, 0), end_time=time(17, 0), break_minutes=0,
        )
        rows = build_day_rows(self.job, "BY", date(2026, 3, 11), date(2026, 3, 11), date(2026, 3, 10))
        self.assertFalse(rows[0]["pending"])
        self.assertEqual(rows[0]["ist"], Decimal("8.00"))

    def test_week_rows_are_clipped_to_range(self):
        from timetracking.periods import build_day_rows, build_week_rows, summarize_rows
        # Juli 2026 beginnt an einem Mittwoch -> erste Woche ist angeschnitten
        rows = build_day_rows(self.job, "BY", date(2026, 7, 1), date(2026, 7, 31), date(2027, 1, 1))
        weeks = build_week_rows(rows)
        self.assertEqual(weeks[0]["week_start"], date(2026, 7, 1))
        self.assertEqual(weeks[-1]["week_end"], date(2026, 7, 31))
        totals = summarize_rows(rows)
        self.assertEqual(sum(w["soll"] for w in weeks), totals["soll"])
        self.assertEqual(sum(w["ist"] for w in weeks), totals["ist"])

    def test_month_bounds_rejects_invalid_month(self):
        from django.http import Http404
        from timetracking.periods import month_bounds
        with self.assertRaises(Http404):
            month_bounds(2026, 13)
        with self.assertRaises(Http404):
            month_bounds(2026, 0)
        with self.assertRaises(Http404):
            month_bounds(1800, 5)

    def test_add_months_crosses_year_boundary(self):
        from timetracking.periods import add_months
        self.assertEqual(add_months(date(2026, 1, 15), -1), date(2025, 12, 1))
        self.assertEqual(add_months(date(2026, 12, 15), 1), date(2027, 1, 1))

    def test_parse_date_param_falls_back(self):
        from timetracking.periods import parse_date_param
        self.assertEqual(parse_date_param("2026-03-05"), date(2026, 3, 5))
        fallback = date(2026, 7, 26)
        self.assertEqual(parse_date_param("kaputt", fallback), fallback)
        self.assertEqual(parse_date_param(None, fallback), fallback)
        self.assertEqual(parse_date_param("2026-02-30", fallback), fallback)


class DashboardNavigationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="navuser", password="pw123456")
        self.client.login(username="navuser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user, work_start_date=date(2026, 1, 1))
        profile.active_job = self.job
        profile.save()

    def test_datum_param_shows_that_week(self):
        response = self.client.get("/timetracking/?datum=2026-03-11")  # Mittwoch
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["week_start"], date(2026, 3, 9))
        self.assertEqual(response.context["week_end"], date(2026, 3, 15))
        self.assertEqual(response.context["week_iso"], 11)
        self.assertFalse(response.context["is_current_week"])

    def test_month_card_follows_focus_date(self):
        response = self.client.get("/timetracking/?datum=2026-03-11")
        self.assertEqual(response.context["month_start"], date(2026, 3, 1))
        self.assertEqual(response.context["month_end"], date(2026, 3, 31))

    def test_invalid_datum_falls_back_to_today(self):
        from timetracking.periods import today_local
        response = self.client.get("/timetracking/?datum=voellig-kaputt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["focus_date"], today_local())
        self.assertTrue(response.context["is_current_week"])

    def test_no_datum_is_current_week(self):
        response = self.client.get("/timetracking/")
        self.assertTrue(response.context["is_current_week"])

    def test_prev_week_disabled_before_job_start(self):
        # Jobstart 2026-01-01; die Woche davor (22.-28.12.2025) hat nichts zu zeigen
        response = self.client.get("/timetracking/?datum=2025-12-31")
        self.assertFalse(response.context["prev_week_available"])
        response = self.client.get("/timetracking/?datum=2026-03-11")
        self.assertTrue(response.context["prev_week_available"])

    def test_month_arrows_cross_year_boundary(self):
        response = self.client.get("/timetracking/?datum=2026-01-15")
        self.assertEqual(response.context["prev_month"], date(2025, 12, 1))
        response = self.client.get("/timetracking/?datum=2026-12-15")
        self.assertEqual(response.context["next_month"], date(2027, 1, 1))


class MonthDetailNavigationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="monthnav", password="pw123456")
        self.client.login(username="monthnav", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user, work_start_date=date(2026, 1, 1))
        profile.active_job = self.job
        profile.save()

    def test_invalid_month_returns_404(self):
        self.assertEqual(self.client.get("/timetracking/monat/2026/13/").status_code, 404)
        self.assertEqual(self.client.get("/timetracking/monat/2026/0/").status_code, 404)

    def test_month_jump_redirects_to_canonical_url(self):
        response = self.client.get("/timetracking/monat/2026/5/?year=2026&month=3")
        self.assertRedirects(
            response, "/timetracking/monat/2026/3/", fetch_redirect_response=False
        )

    def test_month_names_are_german(self):
        """strftime("%B") nahm die System-Locale und lieferte englische Namen."""
        response = self.client.get("/timetracking/monat/2026/3/")
        content = response.content.decode("utf-8")
        self.assertIn("März 2026", content)
        self.assertNotIn("March", content)
        # Auch das Monats-Dropdown
        self.assertIn("Dezember", content)
        self.assertNotIn("December", content)

    def test_prev_next_cross_year_boundary(self):
        response = self.client.get("/timetracking/monat/2026/1/")
        self.assertEqual(response.context["prev_month"], date(2025, 12, 1))
        response = self.client.get("/timetracking/monat/2026/12/")
        self.assertEqual(response.context["next_month"], date(2027, 1, 1))

    def test_month_detail_matches_dashboard_for_same_month(self):
        """Beide Ansichten müssen für denselben Monat dieselbe Zahl zeigen."""
        from timetracking.periods import today_local
        today = today_local()
        dashboard = self.client.get("/timetracking/")
        detail = self.client.get(f"/timetracking/monat/{today.year}/{today.month}/")
        self.assertEqual(dashboard.context["month_soll"], detail.context["month_soll"])
        self.assertEqual(dashboard.context["month_ist"], detail.context["month_ist"])
        self.assertEqual(dashboard.context["month_saldo"], detail.context["month_saldo"])


class EntryNextRedirectTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="nextuser", password="pw123456")
        self.client.login(username="nextuser", password="pw123456")
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = make_job(self.user, work_start_date=date(2026, 1, 1))
        profile.active_job = self.job
        profile.save()

    def _post_entry(self, query=""):
        return self.client.post("/timetracking/eintrag/neu/" + query, {
            "job": self.job.pk,
            "date": "2026-03-11",
            "entry_type": "work",
            "start_time": "09:00",
            "end_time": "17:00",
            "break_minutes": 0,
            "next": "/timetracking/monat/2026/3/" if query else "",
        })

    def test_next_returns_to_origin(self):
        response = self._post_entry("?next=/timetracking/monat/2026/3/")
        self.assertRedirects(
            response, "/timetracking/monat/2026/3/", fetch_redirect_response=False
        )

    def test_external_next_is_rejected(self):
        response = self.client.post(
            "/timetracking/eintrag/neu/?next=https://example.com/phish",
            {
                "job": self.job.pk,
                "date": "2026-03-11",
                "entry_type": "work",
                "start_time": "09:00",
                "end_time": "17:00",
                "break_minutes": 0,
            },
        )
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)

    def test_without_next_falls_back_to_dashboard(self):
        response = self._post_entry()
        self.assertRedirects(response, "/timetracking/", fetch_redirect_response=False)

    def test_delete_honours_next(self):
        from datetime import time
        from timetracking.models import WorkEntry
        entry = WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 3, 12), entry_type="work",
            start_time=time(9, 0), end_time=time(17, 0), break_minutes=0,
        )
        response = self.client.post(
            f"/timetracking/eintrag/{entry.pk}/loeschen/",
            {"next": "/timetracking/monat/2026/3/"},
        )
        self.assertRedirects(
            response, "/timetracking/monat/2026/3/", fetch_redirect_response=False
        )
