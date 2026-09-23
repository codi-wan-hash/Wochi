import re
import uuid
from datetime import date, timedelta
from smtplib import SMTPException
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.core import checks
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django.core import mail

from households.models import Household
from tasks.models import Task
from timetracking.models import UserProfile
from .checks import secret_key_not_public
from .utils import client_ip

User = get_user_model()


def _input_tag(content, name):
    """Das <input>-Tag eines Feldes aus dem HTML holen."""
    match = re.search(rf'<input[^>]*name="{name}"[^>]*>', content)
    assert match, f"Kein Feld {name}"
    return match.group(0)


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
        form = EmailChangeForm(user=self.user, data={"new_email": "fresh@x.de", "password": "pw123456"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_requires_current_password(self):
        """Wer nur eine offene Sitzung hat (Handy geliehen, eingeschleustes
        Skript), darf das Konto nicht über eine neue Adresse übernehmen."""
        from accounts.forms import EmailChangeForm
        for password in ("", "falsch"):
            with self.subTest(password=password):
                form = EmailChangeForm(user=self.user, data={"new_email": "fresh@x.de", "password": password})
                self.assertFalse(form.is_valid())
                self.assertIn("password", form.errors)


class ProfileViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pv", password="pw123456", email="pv@x.de", first_name="Anna")
        self.client.login(username="pv", password="pw123456")

    def test_messages_are_shown_once(self):
        """base.html zeigt die Meldungen schon – das Profil hatte sie doppelt."""
        response = self.client.post("/accounts/profil/", {
            "username": "pv", "first_name": "Anna", "last_name": "",
        }, follow=True)
        self.assertEqual(response.content.decode().count("Profil aktualisiert."), 1)

    def test_links_to_account_deletion(self):
        response = self.client.get("/accounts/profil/")
        self.assertContains(response, reverse("account_delete"))
        self.assertContains(response, "<title>Profil · Wochii</title>")

    def test_username_rename_is_case_insensitively_unique(self):
        User.objects.create_user(username="anna", password="pw123456")
        response = self.client.post("/accounts/profil/", {
            "username": "ANNA", "first_name": "", "last_name": "",
        })
        self.assertContains(response, "Dieser Benutzername ist schon vergeben.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "pv")

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
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(username="ec2", password="pw123456", email="old@x.de")
        self.client.login(username="ec2", password="pw123456")

    def tearDown(self):
        cache.clear()

    def _post(self, password="pw123456", **kwargs):
        return self.client.post(
            "/accounts/profil/email/", {"new_email": "new@x.de", "password": password}, **kwargs
        )

    def test_get_loads_form(self):
        response = self.client.get("/accounts/profil/email/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neue E-Mail")
        self.assertIn('autocomplete="current-password"', _input_tag(response.content.decode(), "password"))

    def test_post_sets_pending_and_sends_mail(self):
        mail.outbox = []
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bestätigung")
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.userprofile.pending_email, "new@x.de")
        self.assertIsNotNone(self.user.userprofile.email_verification_token)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new@x.de", mail.outbox[0].to)

    def test_wrong_password_sends_nothing(self):
        mail.outbox = []
        response = self._post(password="falsch")
        self.assertContains(response, "Das Passwort stimmt nicht.")
        self.assertEqual(len(mail.outbox), 0)
        self.user.userprofile.refresh_from_db()
        self.assertIsNone(self.user.userprofile.pending_email)

    def test_user_without_profile_does_not_crash(self):
        """Ältere Konten haben kein UserProfile – vorher gab das einen 500er."""
        UserProfile.objects.filter(user=self.user).delete()
        self.assertEqual(self.client.get("/accounts/profil/email/").status_code, 200)
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserProfile.objects.get(user=self.user).pending_email, "new@x.de")

    def test_requests_are_limited_per_hour(self):
        mail.outbox = []
        for _ in range(5):
            self._post(password="falsch")
        response = self._post(follow=True)
        self.assertRedirects(response, "/accounts/profil/")
        self.assertContains(response, "schon mehrmals angefordert")
        self.assertEqual(len(mail.outbox), 0)

    def test_send_failure_shows_generic_message_and_logs(self):
        failure = SMTPException("535 Zugang zu smtp.intern.example verweigert")
        with mock.patch("accounts.views.send_mail", side_effect=failure), \
                self.assertLogs("accounts.views", level="ERROR"):
            response = self._post(follow=True)
        self.assertRedirects(response, "/accounts/profil/")
        self.assertContains(response, "konnte gerade nicht gesendet werden")
        self.assertNotContains(response, "smtp.intern.example")
        self.user.userprofile.refresh_from_db()
        self.assertIsNone(self.user.userprofile.pending_email)
        self.assertIsNone(self.user.userprofile.email_verification_token)


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

    def test_user_without_profile_does_not_crash(self):
        UserProfile.objects.filter(user=self.user).delete()
        response = self.client.post("/accounts/profil/email/abbrechen/")
        self.assertRedirects(response, "/accounts/profil/")


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
        # Die Ratenbegrenzung zählt im Cache – ohne Leeren zählten die
        # Anfragen anderer Tests mit.
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username="vergesslich", password="altesPasswort123", email="vergesslich@example.com"
        )

    def tearDown(self):
        cache.clear()

    def _request_reset(self, email, **extra):
        return self.client.post(reverse("password_reset"), {"email": email}, **extra)

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

    def test_throttle_per_address_stops_mail_flood(self):
        for _ in range(3):
            self._request_reset("vergesslich@example.com")
        self.assertEqual(len(mail.outbox), 3)
        # Die vierte Anfrage (auch anders geschrieben, von anderer IP) sieht für
        # den Absender identisch aus, sendet aber nicht.
        response = self._request_reset("VERGESSLICH@example.com", REMOTE_ADDR="10.0.0.99")
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 3)

    def _users(self, count):
        return [
            User.objects.create_user(f"konto{i}", f"konto{i}@example.com", "altesPasswort123")
            for i in range(count)
        ]

    def test_throttle_per_ip(self):
        users = self._users(6)
        for user in users[:5]:
            self._request_reset(user.email)
        self.assertEqual(len(mail.outbox), 5)
        response = self._request_reset(users[5].email)
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 5)

    def test_throttle_uses_last_forwarded_address(self):
        """Den ersten X-Forwarded-For-Eintrag wählt der Client selbst – mit
        wechselnden Werten darf er die Sperre nicht umgehen."""
        users = self._users(6)
        for i, user in enumerate(users):
            self._request_reset(user.email, HTTP_X_FORWARDED_FOR=f"198.51.100.{i}, 203.0.113.7")
        self.assertEqual(len(mail.outbox), 5)


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


class RegisterFormMarkupTest(TestCase):
    """Die Labels der Registrierung müssen mit ihrem Feld verknüpft sein.

    Ohne for-Attribut ist das Label auf dem Smartphone kein Tap-Target,
    was die Trefferfläche pro Feld etwa halbiert.
    """

    def test_labels_are_linked_to_inputs(self):
        response = Client().get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        for field_id in ("id_username", "id_email", "id_password1", "id_password2"):
            self.assertContains(response, f'for="{field_id}"')


class ClientIpTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_uses_last_forwarded_entry(self):
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9", REMOTE_ADDR="10.0.0.1"
        )
        self.assertEqual(client_ip(request), "203.0.113.9")

    def test_single_forwarded_entry(self):
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="203.0.113.9", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(client_ip(request), "203.0.113.9")

    def test_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(self.factory.get("/", REMOTE_ADDR="10.0.0.1")), "10.0.0.1")
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="", REMOTE_ADDR="10.0.0.2")
        self.assertEqual(client_ip(request), "10.0.0.2")


class LoginViewTest(TestCase):
    password = "richtigesPasswort1"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="anna", password=self.password, email="anna@example.com"
        )

    def tearDown(self):
        cache.clear()

    def _login(self, username="anna", password="falsch", client=None, **extra):
        client = client or self.client
        return client.post(reverse("login"), {"username": username, "password": password}, **extra)

    def _fail(self, times, **extra):
        for _ in range(times):
            self.assertContains(self._login(**extra), "stimmt nicht")

    def test_failed_login_does_not_echo_password(self):
        response = self._login(password="GeheimesPasswort!")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "GeheimesPasswort!")
        # Der Benutzername bleibt stehen, damit man nur das Passwort neu tippt.
        self.assertIn('value="anna"', _input_tag(response.content.decode(), "username"))

    def test_field_attributes_for_phones_and_password_managers(self):
        response = self.client.get(reverse("login"))
        content = response.content.decode()
        username = _input_tag(content, "username")
        self.assertIn('autocapitalize="none"', username)
        self.assertIn('autocomplete="username"', username)
        self.assertIn('autocomplete="current-password"', _input_tag(content, "password"))
        self.assertContains(response, "Benutzername oder E-Mail")
        self.assertContains(response, "<title>Anmelden · Wochii</title>")

    def test_login_with_email_ignores_case(self):
        response = self._login(username="ANNA@example.com", password=self.password)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_nine_failures_do_not_block(self):
        self._fail(9)
        response = self._login(password=self.password)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_ten_failures_block_even_the_correct_password(self):
        self._fail(10)
        response = self._login(password=self.password)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zu viele fehlgeschlagene Anmeldeversuche")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_blocked_attempt_does_not_check_password(self):
        self._fail(10)
        with mock.patch("django.contrib.auth.forms.authenticate") as authenticate:
            response = self._login(password=self.password)
        authenticate.assert_not_called()
        self.assertContains(response, "Zu viele fehlgeschlagene Anmeldeversuche")

    def test_block_ignores_username_case(self):
        for i in range(10):
            self._login(username="ANNA" if i % 2 else "anna")
        self.assertContains(self._login(password=self.password), "Zu viele")

    def test_block_is_per_ip_and_username(self):
        self._fail(10)
        User.objects.create_user(username="bert", password=self.password)
        response = self._login(username="bert", password=self.password, client=Client())
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        other_ip = Client(REMOTE_ADDR="10.9.9.9")
        response = self._login(password=self.password, client=other_ip)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_rotating_first_forwarded_entry_does_not_bypass_block(self):
        for i in range(10):
            self._login(HTTP_X_FORWARDED_FOR=f"198.51.100.{i}, 203.0.113.9")
        response = self._login(password=self.password, HTTP_X_FORWARDED_FOR="192.0.2.1, 203.0.113.9")
        self.assertContains(response, "Zu viele")

    def test_register_link_keeps_next(self):
        response = self.client.get(reverse("login") + "?next=/households/")
        self.assertContains(response, 'href="/register/?next=/households/"')
        self.assertContains(response, '<input type="hidden" name="next" value="/households/">')

    def test_login_follows_next(self):
        response = self.client.post(reverse("login") + "?next=/households/", {
            "username": "anna", "password": self.password, "next": "/households/",
        })
        self.assertRedirects(response, "/households/", fetch_redirect_response=False)


class RegisterViewTest(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _data(self, **overrides):
        data = {
            "username": "carla",
            "email": "carla@example.com",
            "password1": "Sicher!Passwort2",
            "password2": "Sicher!Passwort2",
        }
        data.update(overrides)
        return data

    def _register(self, client=None, url=None, **overrides):
        return (client or Client()).post(url or reverse("register"), self._data(**overrides))

    def test_field_attributes(self):
        response = Client().get(reverse("register"))
        content = response.content.decode()
        username = _input_tag(content, "username")
        # Ohne autocapitalize="none" registrierten Handys „Carla“ statt „carla“.
        self.assertIn('autocapitalize="none"', username)
        self.assertIn('class="form-control"', username)
        email = _input_tag(content, "email")
        self.assertIn('autocomplete="email"', email)
        self.assertIn('class="form-control"', email)
        for name in ("password1", "password2"):
            self.assertIn('autocomplete="new-password"', _input_tag(content, name))
        self.assertContains(response, "<title>Registrieren · Wochii</title>")

    def test_register_creates_user_and_goes_to_setup(self):
        response = self._register()
        self.assertRedirects(response, "/households/choose/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="carla", email="carla@example.com").exists())

    def test_email_must_be_unique_ignoring_case(self):
        User.objects.create_user(username="anna", password="pw123456", email="Carla@Example.com")
        response = self._register(email="carla@EXAMPLE.com")
        self.assertContains(response, "Diese E-Mail-Adresse wird bereits verwendet.")
        self.assertFalse(User.objects.filter(username="carla").exists())

    def test_username_must_be_unique_ignoring_case(self):
        User.objects.create_user(username="carla", password="pw123456")
        response = self._register(username="Carla", email="neu@example.com")
        self.assertContains(response, "Dieser Benutzername ist schon vergeben.")
        self.assertEqual(User.objects.filter(username__iexact="carla").count(), 1)

    def test_redirects_to_safe_next_after_registration(self):
        household = Household.objects.create(name="Familie")
        url = f"/households/join/{household.invite_token}/"
        client = Client()
        page = client.get(f"{reverse('register')}?next={url}")
        self.assertContains(page, f'<input type="hidden" name="next" value="{url}">')
        self.assertContains(page, "direkt weiter zu deiner Einladung")
        response = client.post(reverse("register"), {**self._data(), "next": url})
        self.assertRedirects(response, url, fetch_redirect_response=False)

    def test_ignores_external_next(self):
        response = self._register(url=reverse("register") + "?next=https://boese.example.com/")
        self.assertRedirects(response, "/households/choose/", fetch_redirect_response=False)

    def test_registrations_are_limited_per_ip(self):
        for i in range(5):
            response = self._register(username=f"konto{i}", email=f"konto{i}@example.com")
            self.assertEqual(response.status_code, 302)
        response = self._register(username="konto5", email="konto5@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "schon mehrere Konten angelegt")
        self.assertFalse(User.objects.filter(username="konto5").exists())
        # Eine andere Adresse ist nicht betroffen.
        response = self._register(client=Client(REMOTE_ADDR="10.1.1.1"), username="konto6",
                                  email="konto6@example.com")
        self.assertEqual(response.status_code, 302)

    def test_invalid_attempts_do_not_count_towards_limit(self):
        for _ in range(6):
            self.assertEqual(self._register(password2="Tippfehler!2").status_code, 200)
        self.assertEqual(self._register().status_code, 302)


class InviteSignupFlowTest(TestCase):
    """Einladungslink → Anmeldung → Registrierung → zurück zur Einladung."""

    def setUp(self):
        cache.clear()
        owner = User.objects.create_user(username="besitzer", password="pw123456")
        self.household = Household.objects.create(name="Familie Müller")
        self.household.members.add(owner)

    def tearDown(self):
        cache.clear()

    def test_invite_survives_registration(self):
        client = Client()
        join_url = f"/households/join/{self.household.invite_token}/"

        login_page = client.get(join_url, follow=True)
        self.assertContains(login_page, "Du wurdest zu einem Haushalt eingeladen")
        match = re.search(r'href="(/register/\?next=[^"]+)"', login_page.content.decode())
        self.assertIsNotNone(match)

        response = client.post(match.group(1).replace("&amp;", "&"), {
            "username": "neu",
            "email": "neu@example.com",
            "password1": "Sicher!Passwort2",
            "password2": "Sicher!Passwort2",
            "next": join_url,
        })
        self.assertRedirects(response, join_url, fetch_redirect_response=False)

        client.post(join_url)
        new_user = User.objects.get(username="neu")
        self.assertTrue(self.household.members.filter(pk=new_user.pk).exists())


class AccountDeleteViewTest(TestCase):
    password = "richtigesPasswort1"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("anna", "anna@example.com", self.password)
        self.partner = User.objects.create_user("bert", "bert@example.com", "pw123456")
        self.shared = Household.objects.create(name="Familie")
        self.shared.members.add(self.user, self.partner)
        self.solo = Household.objects.create(name="Nur Anna")
        self.solo.members.add(self.user)
        self.client.login(username="anna", password=self.password)
        self.url = reverse("account_delete")

    def tearDown(self):
        cache.clear()

    def test_url(self):
        self.assertEqual(self.url, "/accounts/profil/konto-loeschen/")

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, f"/accounts/login/?next={self.url}", fetch_redirect_response=False)

    def test_page_explains_consequences(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Konto löschen · Wochii</title>")
        self.assertContains(response, "Arbeitszeiterfassung")
        self.assertContains(response, "nicht rückgängig")
        self.assertEqual(list(response.context["households_deleted"]), [self.solo])
        self.assertEqual(list(response.context["households_kept"]), [self.shared])
        self.assertContains(response, "„Nur Anna“")
        self.assertContains(response, "2 Mitglieder")

    def test_wrong_password_keeps_account(self):
        response = self.client.post(self.url, {"password": "falsch"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Das Passwort stimmt nicht.")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_correct_password_deletes_account_and_logs_out(self):
        shared_task = Task.objects.create(
            household=self.shared, title="Einkaufen", due_date=date(2026, 9, 1), created_by=self.user
        )
        Task.objects.create(household=self.solo, title="Privat", due_date=date(2026, 9, 1))

        response = self.client.post(self.url, {"password": self.password}, follow=True)

        self.assertRedirects(response, "/accounts/login/")
        self.assertContains(response, "Dein Konto wurde gelöscht")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Household.objects.filter(pk=self.solo.pk).exists())
        self.assertFalse(Task.objects.filter(title="Privat").exists())
        # Im gemeinsamen Haushalt bleibt alles für die anderen erhalten.
        self.assertTrue(self.shared.members.filter(pk=self.partner.pk).exists())
        shared_task.refresh_from_db()
        self.assertIsNone(shared_task.created_by)

    def test_attempts_are_limited(self):
        for _ in range(5):
            self.client.post(self.url, {"password": "falsch"})
        response = self.client.post(self.url, {"password": self.password}, follow=True)
        self.assertContains(response, "Zu viele Versuche")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())


class SecretKeyCheckTest(SimpleTestCase):
    def _ids(self):
        return [message.id for message in secret_key_not_public(None)]

    @override_settings(DEBUG=False, SECRET_KEY="django-insecure-abc123")
    def test_warns_for_startproject_placeholder(self):
        self.assertIn("accounts.W003", self._ids())

    @override_settings(DEBUG=False, SECRET_KEY="dev-secret-key-only-for-local")
    def test_warns_for_value_from_repository(self):
        self.assertIn("accounts.W003", self._ids())

    @override_settings(DEBUG=False, SECRET_KEY="bitte-einen-langen-zufaelligen-wert-setzen")
    def test_warns_for_value_from_env_example(self):
        self.assertIn("accounts.W003", self._ids())

    @override_settings(DEBUG=False, SECRET_KEY="k2J9-wirklich-zufaellig-8fQpL3xZ7vN1rT5y")
    def test_quiet_for_random_key(self):
        self.assertEqual(self._ids(), [])

    @override_settings(DEBUG=True, SECRET_KEY="django-insecure-abc123")
    def test_quiet_in_debug(self):
        self.assertEqual(self._ids(), [])

    @override_settings(DEBUG=False, SECRET_KEY="django-insecure-abc123")
    def test_is_registered(self):
        ids = [message.id for message in checks.run_checks(tags=[checks.Tags.security])]
        self.assertIn("accounts.W003", ids)


class HomePageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="anna", password="pw123456")
        self.household = Household.objects.create(name="Familie")
        self.household.members.add(self.user)
        self.client.login(username="anna", password="pw123456")

    def test_invite_card_can_share_and_links_to_household_page(self):
        response = self.client.get("/")
        self.assertContains(response, "<title>Übersicht · Wochii</title>")
        self.assertContains(
            response, f'value="http://testserver/households/join/{self.household.invite_token}/"'
        )
        self.assertContains(response, "data-invite-share")
        self.assertContains(response, "data-invite-copy")
        self.assertContains(response, '<a href="/households/" class="btn btn-outline-secondary btn-sm">Haushalt verwalten</a>')

    def test_upcoming_tasks_use_german_dates(self):
        Task.objects.create(household=self.household, title="Rasen", due_date=date(2026, 8, 1))
        self.assertContains(self.client.get("/"), "Sa, 01.08.2026")
