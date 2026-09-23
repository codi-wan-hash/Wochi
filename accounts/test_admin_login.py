from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

User = get_user_model()


class AdminLoginThrottleTest(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser("chef", "chef@example.com", "Sicher!Passwort1")

    def test_admin_login_is_blocked_after_ten_failures(self):
        for _ in range(10):
            self.client.post("/admin/login/", {"username": "chef", "password": "falsch"})
        # Auch mit dem richtigen Passwort geht es jetzt nicht mehr.
        response = self.client.post("/admin/login/", {"username": "chef", "password": "Sicher!Passwort1"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_login_still_works_normally(self):
        response = self.client.post("/admin/login/", {"username": "chef", "password": "Sicher!Passwort1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
