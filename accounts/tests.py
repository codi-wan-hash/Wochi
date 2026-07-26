import re
import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
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


class EmailChangeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="ec2", password="pw123456", email="old@x.de")
        self.client.login(username="ec2", password="pw123456")

    def test_get_loads_form(self):
        response = self.client.get("/accounts/profil/email/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neue E-Mail")

    def test_post_sets_pending_and_sends_mail(self):
        mail.outbox = []
        response = self.client.post("/accounts/profil/email/", {"new_email": "new@x.de"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bestätigung")
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.userprofile.pending_email, "new@x.de")
        self.assertIsNotNone(self.user.userprofile.email_verification_token)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new@x.de", mail.outbox[0].to)


class EmailVerifyViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ev", password="pw123456", email="old@x.de")
        self.token = uuid.uuid4()
        p = self.user.userprofile
        p.pending_email = "new@x.de"
        p.email_verification_token = self.token
        p.email_token_expires_at = timezone.now() + timedelta(hours=24)
        p.save()

    def test_valid_token_updates_email(self):
        response = self.client.get(f"/accounts/profil/email/bestaetigen/{self.token}/")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.email, "new@x.de")
        self.assertIsNone(self.user.userprofile.pending_email)
        self.assertIsNone(self.user.userprofile.email_verification_token)

    def test_expired_token_rejected(self):
        p = self.user.userprofile
        p.email_token_expires_at = timezone.now() - timedelta(hours=1)
        p.save()
        response = self.client.get(f"/accounts/profil/email/bestaetigen/{self.token}/")
        self.assertContains(response, "abgelaufen", status_code=200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@x.de")

    def test_unknown_token_rejected(self):
        bogus = uuid.uuid4()
        response = self.client.get(f"/accounts/profil/email/bestaetigen/{bogus}/")
        self.assertContains(response, "ungültig", status_code=200)


class EmailCancelViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="cancel", password="pw123456")
        self.client.login(username="cancel", password="pw123456")
        p = self.user.userprofile
        p.pending_email = "x@y.de"
        p.email_verification_token = uuid.uuid4()
        p.email_token_expires_at = timezone.now() + timedelta(hours=24)
        p.save()

    def test_post_clears_pending(self):
        response = self.client.post("/accounts/profil/email/abbrechen/")
        self.assertRedirects(response, "/accounts/profil/")
        self.user.userprofile.refresh_from_db()
        self.assertIsNone(self.user.userprofile.pending_email)
        self.assertIsNone(self.user.userprofile.email_verification_token)


class PasswordChangeSmokeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pwc", password="pw123456")
        self.client.login(username="pwc", password="pw123456")

    def test_change_form_loads(self):
        response = self.client.get("/accounts/profil/passwort/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort")

    def test_done_page_loads(self):
        response = self.client.get("/accounts/profil/passwort/erfolg/")
        self.assertEqual(response.status_code, 200)


class PasswordResetFlowTest(TestCase):
    """Der komplette Ablauf „Passwort vergessen“ von der Anfrage bis zum Login."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="vergesslich", password="altesPasswort123", email="vergesslich@example.com"
        )

    def _request_reset(self, email):
        return self.client.post(reverse("password_reset"), {"email": email})

    def _link_from_mail(self):
        body = mail.outbox[0].body
        match = re.search(r"/accounts/passwort-neu/[^/]+/[^/\s]+/", body)
        self.assertIsNotNone(match, f"Kein Reset-Link in der E-Mail:\n{body}")
        return match.group(0)

    def test_form_page_loads(self):
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort vergessen")
        # Nicht die englische Admin-Vorlage
        self.assertTemplateUsed(response, "registration/password_reset_form.html")

    def test_full_reset_flow(self):
        response = self._request_reset("vergesslich@example.com")
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Wochii", mail.outbox[0].subject)

        link = self._link_from_mail()
        # Django leitet auf eine set-password-URL um, bevor das Formular kommt
        response = self.client.get(link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["validlink"])

        response = self.client.post(response.request["PATH_INFO"], {
            "new_password1": "ganzNeuesPasswort456",
            "new_password2": "ganzNeuesPasswort456",
        })
        self.assertRedirects(response, reverse("password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ganzNeuesPasswort456"))
        self.assertTrue(self.client.login(
            username="vergesslich", password="ganzNeuesPasswort456"
        ))

    def test_unknown_email_gives_same_answer_without_mail(self):
        """Die Antwort darf nicht verraten, ob es das Konto gibt."""
        response = self._request_reset("gibtsnicht@example.com")
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_done_page_does_not_confirm_account_exists(self):
        response = self.client.get(reverse("password_reset_done"))
        self.assertContains(response, "Falls ein Konto")

    def test_tampered_token_shows_invalid_page(self):
        self._request_reset("vergesslich@example.com")
        link = self._link_from_mail()
        broken = link[:-5] + "xxxx/"
        response = self.client.get(broken, follow=True)
        self.assertFalse(response.context["validlink"])
        self.assertContains(response, "Link ungültig")

    def test_link_works_only_once(self):
        self._request_reset("vergesslich@example.com")
        link = self._link_from_mail()
        response = self.client.get(link, follow=True)
        self.client.post(response.request["PATH_INFO"], {
            "new_password1": "ganzNeuesPasswort456",
            "new_password2": "ganzNeuesPasswort456",
        })
        # Zweiter Versuch mit demselben Link
        response = self.client.get(link, follow=True)
        self.assertFalse(response.context["validlink"])

    def test_throttle_stops_mail_flood(self):
        cache.clear()
        for _ in range(5):
            self._request_reset("vergesslich@example.com")
        self.assertEqual(len(mail.outbox), 5)
        # Die sechste Anfahrt sieht für den Absender identisch aus, sendet aber nicht
        response = self._request_reset("vergesslich@example.com")
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 5)
        cache.clear()


class AuthUrlNamesTest(TestCase):
    """Regression: django.contrib.auth.urls hatte dieselben Namen registriert
    und überschrieb dabei unsere eigenen Templates."""

    def test_password_change_resolves_to_own_view(self):
        self.assertEqual(reverse("password_change"), "/accounts/profil/passwort/")
        self.assertEqual(reverse("password_change_done"), "/accounts/profil/passwort/erfolg/")

    def test_login_path_unchanged(self):
        self.assertEqual(reverse("login"), "/accounts/login/")
        self.assertEqual(reverse("logout"), "/accounts/logout/")

    def test_password_change_uses_bootstrap_template(self):
        User.objects.create_user(username="stiluser", password="pw12345678")
        self.client.login(username="stiluser", password="pw12345678")
        response = self.client.get(reverse("password_change"))
        self.assertTemplateUsed(response, "accounts/password_change_form.html")

    def test_login_page_links_to_password_reset(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("password_reset"))
