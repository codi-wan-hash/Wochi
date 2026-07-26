from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from households.models import Household
from .models import ShoppingItem

User = get_user_model()


class ShoppingViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="einkauf", password="pw123456")
        self.client.login(username="einkauf", password="pw123456")
        self.household = Household.objects.create(name="Testhaushalt")
        self.household.members.add(self.user)

    def _create_item(self, name="Milch"):
        return ShoppingItem.objects.create(
            household=self.household, name=name, quantity="1 L", added_by=self.user,
        )

    def test_list_renders(self):
        self._create_item()
        response = self.client.get("/shopping/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Milch")

    def test_empty_state_offers_create_link(self):
        response = self.client.get("/shopping/")
        self.assertContains(response, "/shopping/new/")

    def test_create_shows_success_message(self):
        response = self.client.post(
            "/shopping/new/", {"name": "Butter", "quantity": "250 g"}, follow=True
        )
        self.assertTrue(ShoppingItem.objects.filter(name="Butter").exists())
        self.assertContains(response, "hinzugefügt")

    def test_delete_shows_success_message(self):
        item = self._create_item()
        response = self.client.post(f"/shopping/{item.pk}/delete/", follow=True)
        self.assertFalse(ShoppingItem.objects.filter(pk=item.pk).exists())
        self.assertContains(response, "Artikel gelöscht")

    def test_ajax_delete_sends_no_message(self):
        """Bei AJAX würde die Meldung erst beim nächsten Seitenaufruf erscheinen."""
        item = self._create_item()
        response = self.client.post(
            f"/shopping/{item.pk}/delete/", headers={"x-requested-with": "XMLHttpRequest"}
        )
        self.assertEqual(response.json(), {"deleted": True})
        # Kein Nachhall auf der Folgeseite
        self.assertNotContains(self.client.get("/shopping/"), "Artikel gelöscht")

    def test_other_household_item_is_not_reachable(self):
        stranger = User.objects.create_user(username="fremd2", password="pw123456")
        other = Household.objects.create(name="Fremder Haushalt")
        other.members.add(stranger)
        foreign = ShoppingItem.objects.create(
            household=other, name="Geheimzutat", quantity="1", added_by=stranger,
        )
        self.assertEqual(self.client.get(f"/shopping/{foreign.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.post(f"/shopping/{foreign.pk}/toggle/").status_code, 404)
        self.assertNotContains(self.client.get("/shopping/"), "Geheimzutat")

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/shopping/")
        self.assertRedirects(
            response, "/accounts/login/?next=/shopping/", fetch_redirect_response=False
        )
