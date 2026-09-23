from django.contrib.auth import get_user_model
from django.test import Client, TestCase

User = get_user_model()


class ExistingSessionTest(TestCase):
    def test_session_from_before_the_deploy_stays_valid(self):
        """Sitzungen von vor der Umstellung wurden mit ModelBackend angelegt."""
        user = User.objects.create_user("bestand", "bestand@example.com", "Sicher!Passwort1")
        client = Client()
        client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(client.get("/tasks/").status_code, 302)  # ohne Haushalt → Auswahl
        self.assertNotIn("/accounts/login/", client.get("/tasks/")["Location"])

    def test_registration_logs_in_without_error(self):
        response = Client().post("/register/", {
            "username": "neu", "email": "neu@example.com",
            "password1": "Sicher!Passwort1", "password2": "Sicher!Passwort1",
        })
        self.assertEqual(response.status_code, 302)

    def test_profile_saves_for_legacy_case_duplicates(self):
        User.objects.create_user("anna", "a@example.com", "Sicher!Passwort1")
        legacy = User.objects.create_user("Anna", "b@example.com", "Sicher!Passwort1")
        client = Client()
        client.force_login(legacy)
        response = client.post("/accounts/profil/", {"username": "Anna", "first_name": "Anna", "last_name": "B"})
        self.assertEqual(response.status_code, 302)
        legacy.refresh_from_db()
        self.assertEqual(legacy.first_name, "Anna")
