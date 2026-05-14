import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.core import mail

User = get_user_model()


class UserProfileEmailFieldsTest(TestCase):
    def test_pending_email_fields_default_none(self):
        user = User.objects.create_user(username="profilefields", password="pw123456")
        p = user.userprofile
        self.assertIsNone(p.pending_email)
        self.assertIsNone(p.email_verification_token)
        self.assertIsNone(p.email_token_expires_at)

    def test_pending_email_fields_can_be_set(self):
        user = User.objects.create_user(username="setfields", password="pw123456")
        p = user.userprofile
        token = uuid.uuid4()
        p.pending_email = "new@example.com"
        p.email_verification_token = token
        p.email_token_expires_at = timezone.now() + timedelta(hours=24)
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.pending_email, "new@example.com")
        self.assertEqual(p.email_verification_token, token)


class ProfileFormTest(TestCase):
    def test_saves_username_and_names(self):
        from accounts.forms import ProfileForm
        user = User.objects.create_user(username="orig", password="pw123456", first_name="Old", last_name="Name")
        form = ProfileForm(data={"username": "newname", "first_name": "Max", "last_name": "Mustermann"}, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()
        self.assertEqual(user.username, "newname")
        self.assertEqual(user.first_name, "Max")
        self.assertEqual(user.last_name, "Mustermann")


class EmailChangeFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ec", password="pw123456", email="me@old.de")

    def test_rejects_same_email(self):
        from accounts.forms import EmailChangeForm
        form = EmailChangeForm(user=self.user, data={"new_email": "me@old.de"})
        self.assertFalse(form.is_valid())
        self.assertIn("new_email", form.errors)

    def test_rejects_existing_email(self):
        User.objects.create_user(username="other", password="pw123456", email="taken@x.de")
        from accounts.forms import EmailChangeForm
        form = EmailChangeForm(user=self.user, data={"new_email": "taken@x.de"})
        self.assertFalse(form.is_valid())
        self.assertIn("new_email", form.errors)

    def test_accepts_new_unique_email(self):
        from accounts.forms import EmailChangeForm
        form = EmailChangeForm(user=self.user, data={"new_email": "fresh@x.de"})
        self.assertTrue(form.is_valid(), form.errors)


class ProfileViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pv", password="pw123456", email="pv@x.de", first_name="Anna")
        self.client.login(username="pv", password="pw123456")

    def test_get_loads(self):
        response = self.client.get("/accounts/profil/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anna")
        self.assertContains(response, "pv@x.de")

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/accounts/profil/")
        self.assertRedirects(response, "/accounts/login/?next=/accounts/profil/")

    def test_post_updates_user_fields(self):
        response = self.client.post("/accounts/profil/", {
            "username": "pv",
            "first_name": "Bertha",
            "last_name": "Beispiel",
        })
        self.assertRedirects(response, "/accounts/profil/")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Bertha")
        self.assertEqual(self.user.last_name, "Beispiel")
