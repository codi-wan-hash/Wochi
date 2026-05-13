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
