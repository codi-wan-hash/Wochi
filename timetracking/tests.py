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
        # May 4-8 2026 (Mon-Fri), no holidays in Bayern that week
        days = get_soll_days_in_range(date(2026, 5, 4), date(2026, 5, 8), "BY")
        self.assertEqual(len(days), 5)

    def test_saldo_positive(self):
        from timetracking.utils import calculate_total_saldo
        from timetracking.models import WorkEntry
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
        from timetracking.models import WorkEntry

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
