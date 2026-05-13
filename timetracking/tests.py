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
