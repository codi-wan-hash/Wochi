from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from households.models import Household
from .models import FrequentItem, ShoppingItem, ShoppingSession, Store, StoreItemOrder

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

    def test_list_keeps_ids_used_by_shopping_js(self):
        """static/js/shopping.js greift über diese IDs auf die Liste zu.
        Werden sie beim Umbau umbenannt, brechen Abhaken, Hinzufügen und
        Rückgängig still."""
        self._create_item()
        response = self.client.get("/shopping/")
        for marker in ('id="shopping-list-body"', 'id="open-items"', 'id="bought-items"',
                       'id="bought-section"', 'id="quick-add"', 'id="id_name"', 'id="id_quantity"',
                       'id="clear-bought-form"', "js/shopping.js"):
            self.assertContains(response, marker)

    def test_edit_updates_item_instead_of_creating_duplicate(self):
        item = self._create_item()
        response = self.client.post(f"/shopping/{item.pk}/edit/", {"name": "Hafermilch", "quantity": "2 L"})
        self.assertRedirects(response, "/shopping/", fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertEqual((item.name, item.quantity), ("Hafermilch", "2 L"))
        self.assertEqual(ShoppingItem.objects.count(), 1)

    def test_edit_page_does_not_post_to_create_url(self):
        item = self._create_item()
        self.assertNotContains(self.client.get(f"/shopping/{item.pk}/edit/"), "createUrl")

    def test_toggle_and_end_require_post(self):
        item = self._create_item()
        self.assertEqual(self.client.get(f"/shopping/{item.pk}/toggle/").status_code, 405)
        self.assertEqual(self.client.get("/shopping/end/").status_code, 405)
        item.refresh_from_db()
        self.assertFalse(item.is_bought)

    def test_end_shopping_removes_bought_items(self):
        store = Store.objects.create(household=self.household, name="Rewe")
        ShoppingSession.objects.create(household=self.household, store=store, started_by=self.user)
        bought = self._create_item("Brot")
        bought.is_bought = True
        bought.save()
        self._create_item("Käse")
        response = self.client.post("/shopping/end/", follow=True)
        self.assertContains(response, "1 erledigte Artikel")
        self.assertEqual(list(ShoppingItem.objects.values_list("name", flat=True)), ["Käse"])
        self.assertFalse(ShoppingSession.objects.filter(ended_at__isnull=True).exists())

    def test_clear_bought_via_ajax(self):
        bought = self._create_item("Brot")
        bought.is_bought = True
        bought.save()
        response = self.client.post("/shopping/clear-bought/", headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(response.json(), {"removed": 1})

    def test_readding_bought_item_puts_it_back_on_the_list(self):
        bought = self._create_item("Brot")
        bought.is_bought = True
        bought.save()
        self.client.post("/shopping/new/", {"name": "brot", "quantity": "2"},
                         headers={"x-requested-with": "XMLHttpRequest"})
        bought.refresh_from_db()
        self.assertFalse(bought.is_bought)
        self.assertEqual(bought.quantity, "2")
        self.assertEqual(ShoppingItem.objects.count(), 1)

    def test_ajax_add_returns_escaped_row(self):
        response = self.client.post("/shopping/new/", {"name": "<img src=x onerror=alert(1)>", "quantity": ""},
                                    headers={"x-requested-with": "XMLHttpRequest"})
        html = response.json()["html"]
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_partial_returns_only_list(self):
        self._create_item()
        response = self.client.get("/shopping/?partial=1")
        self.assertContains(response, 'id="shopping-list-body"')
        self.assertNotContains(response, "<html")

    def test_new_store_with_too_long_name_shows_error(self):
        response = self.client.post("/shopping/start/", {"action": "new", "name": "x" * 201, "location": ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Store.objects.exists())
        self.assertFalse(ShoppingSession.objects.exists())

    def test_toggle_learns_store_order_during_session(self):
        store = Store.objects.create(household=self.household, name="Rewe")
        ShoppingSession.objects.create(household=self.household, store=store, started_by=self.user)
        item = self._create_item("Äpfel")
        self.client.post(f"/shopping/{item.pk}/toggle/", headers={"x-requested-with": "XMLHttpRequest"})
        self.assertTrue(StoreItemOrder.objects.filter(store=store, item_name="äpfel").exists())

    def test_list_query_count_does_not_grow_with_items(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._create_item("Erster")
        self.client.get("/shopping/")  # Session warm
        with CaptureQueriesContext(connection) as one_item:
            self.client.get("/shopping/")
        for n in range(10):
            self._create_item(f"Artikel {n}")
        with CaptureQueriesContext(connection) as many_items:
            self.client.get("/shopping/")
        self.assertEqual(len(many_items), len(one_item))


class ShoppingServicesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dienst", password="pw123456")
        self.household = Household.objects.create(name="Dienst")
        self.household.members.add(self.user)

    def test_frequent_items_are_counted_and_capped(self):
        from . import services
        ShoppingItem.objects.create(household=self.household, name="Milch", added_by=self.user)
        ShoppingItem.objects.create(household=self.household, name="milch ", added_by=self.user)
        entry = FrequentItem.objects.get(household=self.household)
        self.assertEqual((entry.name_key, entry.times_added), ("milch", 2))
        with self.settings():
            original = services.FREQUENT_ITEMS_LIMIT
            services.FREQUENT_ITEMS_LIMIT = 3
            try:
                for n in range(5):
                    services.record_frequent_item(self.household, f"Neu {n}")
            finally:
                services.FREQUENT_ITEMS_LIMIT = original
        self.assertEqual(FrequentItem.objects.filter(household=self.household).count(), 3)

    def test_add_ingredients_merges_with_open_items(self):
        from . import services
        ShoppingItem.objects.create(household=self.household, name="Mehl", quantity="200 g", added_by=self.user)
        added, merged = services.add_ingredients(
            self.household, self.user, [("mehl", "300 g"), ("Eier", "3"), ("Eier", "2"), ("", "1")]
        )
        self.assertEqual((added, merged), (1, 2))
        self.assertEqual(ShoppingItem.objects.get(name="Mehl").quantity, "500 g")
        self.assertEqual(ShoppingItem.objects.get(name="Eier").quantity, "5")

    def test_forgotten_session_ends_automatically(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import services
        user = User.objects.create_user(username="vergesslich", password="pw123456")
        household = Household.objects.create(name="Vergesslich")
        household.members.add(user)
        store = Store.objects.create(household=household, name="Rewe")
        session = ShoppingSession.objects.create(household=household, store=store, started_by=user)
        ShoppingSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(hours=9))
        self.assertIsNone(services.active_session(household))
        session.refresh_from_db()
        self.assertIsNotNone(session.ended_at)

