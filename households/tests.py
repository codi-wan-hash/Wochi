from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import Household

User = get_user_model()


class HouseholdJoinTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="neuling", password="pw123456")
        self.client.login(username="neuling", password="pw123456")

    def test_create_shows_success_message(self):
        response = self.client.post(
            "/households/choose/", {"action": "create", "name": "WG Hauptstraße"}, follow=True
        )
        self.assertTrue(self.user.households.filter(name="WG Hauptstraße").exists())
        self.assertContains(response, "wurde erstellt")

    def test_join_via_token_shows_success_message(self):
        owner = User.objects.create_user(username="besitzer", password="pw123456")
        household = Household.objects.create(name="Bestandshaushalt")
        household.members.add(owner)

        response = self.client.post(
            "/households/choose/",
            {"action": "join", "invite_token": str(household.invite_token)},
            follow=True,
        )
        self.assertTrue(self.user.households.filter(pk=household.pk).exists())
        self.assertContains(response, "beigetreten")

    def test_invalid_token_shows_error(self):
        response = self.client.post(
            "/households/choose/",
            {"action": "join", "invite_token": "11111111-1111-1111-1111-111111111111"},
        )
        self.assertContains(response, "Ungültiger Einladungstoken")
        self.assertFalse(self.user.households.exists())

    def test_join_via_link_requires_login(self):
        household = Household.objects.create(name="Linkhaushalt")
        self.client.logout()
        url = f"/households/join/{household.invite_token}/"
        response = self.client.get(url)
        self.assertRedirects(
            response, f"/accounts/login/?next={url}", fetch_redirect_response=False
        )
