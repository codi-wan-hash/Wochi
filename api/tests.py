import uuid
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from households.models import Household
from households.utils import get_current_household
from meals.models import Ingredient, MealPlan, Recipe
from shopping.models import FrequentItem, ShoppingItem, ShoppingSession, Store, StoreItemOrder
from tasks.models import Task
from .models import PushToken
from .push import deliver

User = get_user_model()

# Throttling würde viele schnelle Test-Requests blockieren; die Raten selbst
# werden in ThrottleTest gezielt geprüft.
NO_THROTTLE = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["api.authentication.WochiiJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": [],
}


def login(client, user, password="Sicher!Passwort1"):
    response = client.post("/api/auth/login/", {"username": user.username, "password": password}, format="json")
    assert response.status_code == 200, response.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return response.data


class ApiTestCase(TestCase):
    password = "Sicher!Passwort1"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("anna", "anna@example.com", self.password)
        self.other = User.objects.create_user("ben", "ben@example.com", self.password)
        self.household = Household.objects.create(name="Familie")
        self.household.members.add(self.user, self.other)
        login(self.client, self.user, self.password)
        patcher = mock.patch("api.views.notify_household")
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class ShoppingSyncTest(ApiTestCase):
    def sync(self, ops=None, household_id=None):
        return self.client.post(
            "/api/shopping/sync/",
            {"household_id": household_id or self.household.pk, "ops": ops or []},
            format="json",
        )

    def op(self, type_, **fields):
        return {"op_id": str(uuid.uuid4()), "type": type_, **fields}

    def test_pull_without_ops_returns_state(self):
        ShoppingItem.objects.create(household=self.household, name="Milch", added_by=self.user)
        response = self.sync()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["name"] for i in response.data["items"]], ["Milch"])
        self.assertIsNone(response.data["session"])
        self.assertIn("Milch", response.data["suggestions"])

    def test_add_is_idempotent(self):
        client_id = str(uuid.uuid4())
        add = self.op("add", client_id=client_id, name=" Brot ", quantity="1")
        first = self.sync([add])
        second = self.sync([add])  # Antwort ging verloren, App sendet erneut
        self.assertEqual(first.data["results"][0]["status"], "ok")
        self.assertEqual(second.data["results"][0]["status"], "ok")
        self.assertEqual(ShoppingItem.objects.filter(household=self.household).count(), 1)
        item = ShoppingItem.objects.get()
        self.assertEqual((item.name, str(item.client_id), item.added_by), ("Brot", client_id, self.user))
        self.assertEqual(first.data["items"][0]["client_id"], client_id)

    def test_offline_session_learns_store_order_in_check_order(self):
        store = Store.objects.create(household=self.household, name="Rewe")
        items = [
            ShoppingItem.objects.create(household=self.household, name=n, added_by=self.user)
            for n in ("Äpfel", "Butter", "Käse")
        ]
        session_id = str(uuid.uuid4())
        ops = [self.op("start_session", client_id=session_id, store_id=store.pk)]
        for item in (items[2], items[0], items[1]):  # im Laden: Käse, Äpfel, Butter
            ops.append(self.op("set_bought", item={"id": item.pk}, is_bought=True))
        response = self.sync(ops)
        self.assertTrue(all(r["status"] == "ok" for r in response.data["results"]))
        orders = dict(StoreItemOrder.objects.filter(store=store).values_list("item_name", "avg_position"))
        self.assertEqual(orders, {"käse": 1, "äpfel": 2, "butter": 3})
        self.assertEqual(response.data["session"]["client_id"], session_id)

    def test_set_bought_is_absolute_not_toggle(self):
        item = ShoppingItem.objects.create(household=self.household, name="Eier", added_by=self.user)
        set_true = self.op("set_bought", item={"id": item.pk}, is_bought=True)
        self.sync([set_true])
        self.sync([set_true])  # erneut gesendet: bleibt gekauft
        item.refresh_from_db()
        self.assertTrue(item.is_bought)

    def test_ops_on_items_created_offline_use_client_id(self):
        client_id = str(uuid.uuid4())
        response = self.sync([
            self.op("add", client_id=client_id, name="Tee"),
            self.op("update", item={"client_id": client_id}, quantity="2 Packungen"),
            self.op("set_bought", item={"client_id": client_id}, is_bought=True),
        ])
        self.assertEqual([r["status"] for r in response.data["results"]], ["ok", "ok", "ok"])
        item = ShoppingItem.objects.get(client_id=client_id)
        self.assertEqual(item.quantity, "2 Packungen")
        self.assertTrue(item.is_bought)

    def test_deleted_item_is_skipped_not_error(self):
        response = self.sync([
            self.op("set_bought", item={"id": 999999}, is_bought=True),
            self.op("delete", items=[{"id": 999999}]),
        ])
        self.assertEqual([r["status"] for r in response.data["results"]], ["skipped", "skipped"])

    def test_invalid_op_does_not_block_others(self):
        response = self.sync([
            self.op("add", client_id="kein-uuid", name="X"),
            self.op("explode"),
            {"type": "add"},
            "kaputt",
            self.op("add", client_id=str(uuid.uuid4()), name="Salz"),
        ])
        statuses = [r["status"] for r in response.data["results"]]
        self.assertEqual(statuses, ["error", "error", "error", "error", "ok"])
        self.assertTrue(ShoppingItem.objects.filter(name="Salz").exists())

    def test_end_session_only_ends_the_given_session(self):
        store = Store.objects.create(household=self.household, name="Aldi")
        old = ShoppingSession.objects.create(household=self.household, store=store, started_by=self.user,
                                             client_id=uuid.uuid4())
        old.end()
        current = ShoppingSession.objects.create(household=self.household, store=store, started_by=self.other)
        response = self.sync([self.op("end_session", session={"client_id": str(old.client_id)})])
        self.assertEqual(response.data["results"][0]["status"], "skipped")
        current.refresh_from_db()
        self.assertIsNone(current.ended_at)

    def test_start_session_while_other_running_is_skipped(self):
        store = Store.objects.create(household=self.household, name="Aldi")
        running = ShoppingSession.objects.create(household=self.household, store=store, started_by=self.other)
        response = self.sync([self.op("start_session", client_id=str(uuid.uuid4()), store_name="Lidl")])
        self.assertEqual(response.data["results"][0]["status"], "skipped")
        self.assertEqual(response.data["session"]["id"], running.pk)

    def test_start_session_with_new_store_name(self):
        response = self.sync([self.op("start_session", client_id=str(uuid.uuid4()), store_name="Edeka",
                                      store_location="Bahnhof")])
        self.assertEqual(response.data["results"][0]["status"], "ok")
        self.assertEqual(response.data["session"]["store"]["name"], "Edeka")

    def test_snapshot_contains_store_order_for_open_items(self):
        store = Store.objects.create(household=self.household, name="Rewe")
        ShoppingItem.objects.create(household=self.household, name="Milch", added_by=self.user)
        StoreItemOrder.objects.create(store=store, item_name="milch", avg_position=4, times_seen=1)
        StoreItemOrder.objects.create(store=store, item_name="nicht auf der liste", avg_position=1, times_seen=1)
        response = self.sync()
        self.assertEqual(response.data["stores"][0]["item_order"], {"milch": 4})

    def test_foreign_household_is_forbidden(self):
        foreign = Household.objects.create(name="Fremd")
        response = self.sync([self.op("add", client_id=str(uuid.uuid4()), name="X")], household_id=foreign.pk)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ShoppingItem.objects.filter(household=foreign).exists())

    def test_ops_go_to_named_household_not_current(self):
        """Wechselt jemand im Web den Haushalt, landen offline gesammelte
        Änderungen trotzdem im Haushalt, in dem sie gemacht wurden."""
        second = Household.objects.create(name="Zweiter")
        second.members.add(self.user)
        self.client.post(f"/api/households/{second.pk}/activate/")
        self.sync([self.op("add", client_id=str(uuid.uuid4()), name="Kaffee")])
        self.assertTrue(ShoppingItem.objects.filter(household=self.household, name="Kaffee").exists())
        self.assertFalse(ShoppingItem.objects.filter(household=second).exists())

    def test_missing_household_or_bad_ops(self):
        self.assertEqual(self.client.post("/api/shopping/sync/", {"ops": []}, format="json").status_code, 400)
        response = self.client.post("/api/shopping/sync/", {"household_id": self.household.pk, "ops": "x"},
                                    format="json")
        self.assertEqual(response.status_code, 400)

    def test_adds_are_announced_in_one_notification(self):
        self.sync([self.op("add", client_id=str(uuid.uuid4()), name=n) for n in ("A", "B", "C")])
        self.assertEqual(self.notify.call_count, 1)
        self.assertIn("3 Artikel", self.notify.call_args.args[3])


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class ShoppingLegacyEndpointTest(ApiTestCase):
    def test_merge_accepts_extra_quantity_from_old_apps(self):
        item = ShoppingItem.objects.create(household=self.household, name="Mehl", quantity="200 g",
                                           added_by=self.user)
        response = self.client.post(f"/api/shopping/{item.pk}/merge/", {"extra_quantity": "300 g"})
        self.assertEqual(response.data["quantity"], "500 g")

    def test_merged_quantity_is_truncated_to_field_length(self):
        item = ShoppingItem.objects.create(household=self.household, name="Gewürze", quantity="x" * 95,
                                           added_by=self.user)
        response = self.client.post(f"/api/shopping/{item.pk}/merge/", {"quantity": "1 Prise"}, format="json")
        self.assertLessEqual(len(response.data["quantity"]), 100)

    def test_end_removes_bought_items(self):
        store = Store.objects.create(household=self.household, name="Rewe")
        ShoppingSession.objects.create(household=self.household, store=store, started_by=self.user)
        ShoppingItem.objects.create(household=self.household, name="Gekauft", is_bought=True, added_by=self.user)
        ShoppingItem.objects.create(household=self.household, name="Offen", added_by=self.user)
        response = self.client.post("/api/shopping/end/")
        self.assertEqual(response.data["removed"], 1)
        self.assertEqual(list(ShoppingItem.objects.values_list("name", flat=True)), ["Offen"])

    def test_suggestions_survive_clearing_bought_items(self):
        ShoppingItem.objects.create(household=self.household, name="Oliven", is_bought=True, added_by=self.user)
        self.client.post("/api/shopping/clear-bought/")
        self.assertFalse(ShoppingItem.objects.exists())
        self.assertTrue(FrequentItem.objects.filter(household=self.household, name="Oliven").exists())


@override_settings(REST_FRAMEWORK=NO_THROTTLE, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthTest(ApiTestCase):
    def test_login_with_email_and_other_case(self):
        anon = APIClient()
        for username in ("anna@example.com", "ANNA@example.com", "Anna"):
            response = anon.post("/api/auth/login/", {"username": username, "password": self.password},
                                 format="json")
            self.assertEqual(response.status_code, 200, username)

    def test_register_rejects_weak_password_and_duplicates(self):
        anon = APIClient()
        weak = anon.post("/api/auth/register/", {"username": "carl", "email": "carl@example.com",
                                                 "password": "12345678"}, format="json")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("password", weak.data)
        dup = anon.post("/api/auth/register/", {"username": "ANNA", "email": "ANNA@example.com",
                                                "password": "Sicher!Passwort2"}, format="json")
        self.assertEqual(dup.status_code, 400)
        self.assertIn("username", dup.data)
        self.assertIn("email", dup.data)
        missing_email = anon.post("/api/auth/register/", {"username": "dora", "password": "Sicher!Passwort2"},
                                  format="json")
        self.assertIn("email", missing_email.data)

    def test_password_change_revokes_other_devices(self):
        other_device = APIClient()
        tokens = login(other_device, self.user, self.password)
        response = self.client.post("/api/auth/password-change/",
                                    {"old_password": self.password, "new_password": "Neues!Passwort9"},
                                    format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(other_device.get("/api/auth/me/").status_code, 401)
        refresh = APIClient().post("/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(refresh.status_code, 401)
        # Dieses Gerät bekommt neue Tokens und bleibt angemeldet.
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_password_change_requires_old_password(self):
        response = self.client.post("/api/auth/password-change/",
                                    {"old_password": "falsch", "new_password": "Neues!Passwort9"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_refresh_rotates_token(self):
        tokens = login(APIClient(), self.user, self.password)
        response = APIClient().post("/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("refresh", response.data)

    def test_legacy_tokens_without_fingerprint_still_work(self):
        legacy = RefreshToken.for_user(self.user)  # ohne pwh-Claim, wie vor dem Update
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {legacy.access_token}")
        self.assertEqual(client.get("/api/auth/me/").status_code, 200)
        refreshed = APIClient().post("/api/auth/refresh/", {"refresh": str(legacy)}, format="json")
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("pwh", RefreshToken(refreshed.data["refresh"]).payload)

    def test_me_contains_own_email_but_members_do_not(self):
        self.assertEqual(self.client.get("/api/auth/me/").data["email"], "anna@example.com")
        members = self.client.get("/api/households/members/").data
        self.assertTrue(all("email" not in m for m in members))

    def test_password_reset_sends_mail_but_never_reveals_accounts(self):
        anon = APIClient()
        known = anon.post("/api/auth/password-reset/", {"email": "anna@example.com"}, format="json")
        unknown = anon.post("/api/auth/password-reset/", {"email": "nobody@example.com"}, format="json")
        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/passwort-neu/", mail.outbox[0].body)
        self.assertIn("anna", mail.outbox[0].body)

    def test_password_reset_is_limited_per_address(self):
        anon = APIClient()
        for _ in range(5):
            anon.post("/api/auth/password-reset/", {"email": "anna@example.com"}, format="json")
        self.assertEqual(len(mail.outbox), 3)

    def test_delete_account_keeps_shared_data(self):
        task = Task.objects.create(household=self.household, title="Müll", due_date=date.today(),
                                   created_by=self.user)
        recipe = Recipe.objects.create(household=self.household, title="Suppe", created_by=self.user)
        item = ShoppingItem.objects.create(household=self.household, name="Salz", added_by=self.user)
        alone = Household.objects.create(name="Nur Anna")
        alone.members.add(self.user)

        wrong = self.client.post("/api/auth/delete-account/", {"password": "falsch"}, format="json")
        self.assertEqual(wrong.status_code, 400)
        response = self.client.post("/api/auth/delete-account/", {"password": self.password}, format="json")
        self.assertEqual(response.status_code, 204)

        self.assertFalse(User.objects.filter(username="anna").exists())
        for obj in (task, recipe, item):
            obj.refresh_from_db()
        self.assertIsNone(task.created_by)
        self.assertIsNone(recipe.created_by)
        self.assertIsNone(item.added_by)
        self.assertFalse(Household.objects.filter(pk=alone.pk).exists())
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class HouseholdApiTest(ApiTestCase):
    def test_list_marks_current_and_puts_it_first(self):
        newer = Household.objects.create(name="Aaa zuerst alphabetisch")
        newer.members.add(self.user)
        self.client.post(f"/api/households/{newer.pk}/activate/")
        data = self.client.get("/api/households/").data
        self.assertEqual(data[0]["id"], newer.pk)
        self.assertTrue(data[0]["is_current"])
        self.assertFalse(data[1]["is_current"])

    def test_join_with_full_link_activates_household(self):
        target = Household.objects.create(name="Neu")
        link = f"Tritt bei: https://wochii.de/households/join/{target.invite_token}/"
        response = self.client.post("/api/households/join/", {"token": link}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_current"])
        self.assertEqual(get_current_household(self.user), target)

    def test_join_with_garbage_is_400_not_500(self):
        response = self.client.post("/api/households/join/", {"token": "kein-token"}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/households/join/", {"token": str(uuid.uuid4())}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_create_activates_new_household(self):
        response = self.client.post("/api/households/", {"name": "WG"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(get_current_household(self.user).name, "WG")
        too_long = self.client.post("/api/households/", {"name": "x" * 101}, format="json")
        self.assertEqual(too_long.status_code, 400)

    def test_leave_last_member_deletes_household(self):
        alone = Household.objects.create(name="Allein")
        alone.members.add(self.user)
        ShoppingItem.objects.create(household=alone, name="Brot", added_by=self.user)
        response = self.client.post(f"/api/households/{alone.pk}/leave/")
        self.assertEqual(response.data, {"deleted": True})
        self.assertFalse(Household.objects.filter(pk=alone.pk).exists())
        shared = self.client.post(f"/api/households/{self.household.pk}/leave/")
        self.assertEqual(shared.data, {"deleted": False})
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())

    def test_regenerate_invite_invalidates_old_link(self):
        old = self.household.invite_token
        response = self.client.post(f"/api/households/{self.household.pk}/invite/regenerate/")
        self.assertNotEqual(response.data["invite_token"], str(old))
        joiner = User.objects.create_user("carl", "carl@example.com", self.password)
        client = APIClient()
        login(client, joiner, self.password)
        self.assertEqual(client.post("/api/households/join/", {"token": str(old)}, format="json").status_code, 404)

    def test_remove_member(self):
        response = self.client.post(f"/api/households/{self.household.pk}/members/{self.other.pk}/remove/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.household.members.filter(pk=self.other.pk).exists())
        self_remove = self.client.post(f"/api/households/{self.household.pk}/members/{self.user.pk}/remove/")
        self.assertEqual(self_remove.status_code, 400)

    def test_foreign_household_actions_are_404(self):
        foreign = Household.objects.create(name="Fremd")
        for url in ("activate", "leave", "invite/regenerate"):
            self.assertEqual(self.client.post(f"/api/households/{foreign.pk}/{url}/").status_code, 404)


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class TaskApiTest(ApiTestCase):
    def test_recurring_toggle_back_and_forth_creates_one_follow_up(self):
        task = Task.objects.create(household=self.household, title="Müll", due_date=date(2026, 9, 22),
                                   recurrence="weekly", created_by=self.user)
        task.assigned_to.add(self.other)
        for _ in range(3):  # erledigt → offen → erledigt
            self.client.post(f"/api/tasks/{task.pk}/toggle/")
        follow_ups = Task.objects.filter(title="Müll").exclude(pk=task.pk)
        self.assertEqual(follow_ups.count(), 1)
        self.assertEqual(follow_ups.get().due_date, date(2026, 9, 29))
        self.assertEqual(list(follow_ups.get().assigned_to.all()), [self.other])

    def test_toggle_with_target_status_is_idempotent(self):
        task = Task.objects.create(household=self.household, title="Bad putzen", due_date=date.today(),
                                   status="done", created_by=self.user)
        # Jemand anders hat schon erledigt; die App mit altem Stand will "done".
        response = self.client.post(f"/api/tasks/{task.pk}/toggle/", {"status": "done"}, format="json")
        self.assertEqual(response.data["status"], "done")
        task.refresh_from_db()
        self.assertEqual(task.status, "done")
        # Ohne status (alte App) wird weiterhin umgeschaltet.
        self.assertEqual(self.client.post(f"/api/tasks/{task.pk}/toggle/").data["status"], "open")

    def test_list_contains_all_open_tasks_even_with_many_done(self):
        for i in range(120):
            Task.objects.create(household=self.household, title=f"Alt {i}", due_date=date(2025, 1, 1),
                                status="done", created_by=self.user)
        Task.objects.create(household=self.household, title="Neu", due_date=date.today(), created_by=self.user)
        titles = [t["title"] for t in self.client.get("/api/tasks/").data]
        self.assertEqual(titles[0], "Neu")
        self.assertEqual(len(titles), 1 + 50)

    def test_clear_done(self):
        Task.objects.create(household=self.household, title="Fertig", due_date=date.today(), status="done",
                            created_by=self.user)
        Task.objects.create(household=self.household, title="Offen", due_date=date.today(), created_by=self.user)
        response = self.client.post("/api/tasks/clear-done/")
        self.assertEqual(response.data["deleted"], 1)
        self.assertEqual(list(Task.objects.values_list("title", flat=True)), ["Offen"])


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class MealApiTest(ApiTestCase):
    def test_plan_by_title_creates_recipe(self):
        response = self.client.post("/api/meals/", {"date": "2026-09-24", "meal_type": "dinner",
                                                    "recipe_title": "Pizza bestellen"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["recipe"]["title"], "Pizza bestellen")
        again = self.client.post("/api/meals/", {"date": "2026-09-25", "meal_type": "dinner",
                                                 "recipe_title": "pizza bestellen"}, format="json")
        self.assertEqual(again.status_code, 201)
        self.assertEqual(Recipe.objects.filter(household=self.household).count(), 1)

    def test_taken_slot_is_400_not_500(self):
        recipe = Recipe.objects.create(household=self.household, title="Suppe", created_by=self.user)
        MealPlan.objects.create(household=self.household, date=date(2026, 9, 24), meal_type="lunch", recipe=recipe)
        response = self.client.post("/api/meals/", {"date": "2026-09-24", "meal_type": "lunch",
                                                    "recipe_title": "Neu"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Recipe.objects.filter(title="Neu").exists())

    def test_duplicate_recipe_title_is_400_not_500(self):
        Recipe.objects.create(household=self.household, title="Suppe", created_by=self.user)
        response = self.client.post("/api/recipes/", {"title": "suppe"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_invalid_date_filter_is_ignored_not_500(self):
        self.assertEqual(self.client.get("/api/meals/?from=kaputt").status_code, 200)
        response = self.client.post("/api/meals/to-shopping/", {"from": "kaputt"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_week_to_shopping_merges_duplicates(self):
        recipe = Recipe.objects.create(household=self.household, title="Kuchen", created_by=self.user)
        Ingredient.objects.create(recipe=recipe, name="Mehl", quantity="200 g")
        MealPlan.objects.create(household=self.household, date=date(2026, 9, 24), meal_type="lunch", recipe=recipe)
        MealPlan.objects.create(household=self.household, date=date(2026, 9, 25), meal_type="lunch", recipe=recipe)
        response = self.client.post("/api/meals/to-shopping/", {"from": "2026-09-24", "to": "2026-09-30"},
                                    format="json")
        self.assertEqual(response.data, {"added": 1, "merged": 1})
        self.assertEqual(ShoppingItem.objects.get().quantity, "400 g")


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class PushTest(ApiTestCase):
    def test_token_moves_to_last_logged_in_account(self):
        self.client.post("/api/push/register/", {"token": "ExponentPushToken[abc]"}, format="json")
        other = APIClient()
        login(other, self.other, self.password)
        other.post("/api/push/register/", {"token": "ExponentPushToken[abc]"}, format="json")
        self.assertEqual(list(PushToken.objects.values_list("user__username", flat=True)), ["ben"])

    def test_unregister(self):
        self.client.post("/api/push/register/", {"token": "ExponentPushToken[abc]"}, format="json")
        self.client.post("/api/push/unregister/", {"token": "ExponentPushToken[abc]"}, format="json")
        self.assertFalse(PushToken.objects.exists())

    def test_deliver_removes_uninstalled_devices(self):
        PushToken.objects.create(user=self.user, token="t-alt")
        PushToken.objects.create(user=self.other, token="t-ok")
        response = mock.Mock()
        response.json.return_value = {"data": [
            {"status": "error", "details": {"error": "DeviceNotRegistered"}},
            {"status": "ok"},
        ]}
        with mock.patch("api.push.httpx.post", return_value=response), \
                mock.patch("api.push.connection.close"):
            deliver([{"to": "t-alt"}, {"to": "t-ok"}])
        self.assertEqual(list(PushToken.objects.values_list("token", flat=True)), ["t-ok"])


class ThrottleTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_login_is_throttled(self):
        client = APIClient()
        codes = [
            client.post("/api/auth/login/", {"username": "x", "password": "y"}, format="json").status_code
            for _ in range(7)
        ]
        self.assertIn(429, codes)


@override_settings(REST_FRAMEWORK=NO_THROTTLE)
class AppSyncContractTest(ApiTestCase):
    """Operationen genau so, wie wochi-app/src/offline/ShoppingStore.js sie baut."""

    def test_full_offline_trip_as_the_app_sends_it(self):
        now = "2026-09-23T10:00:00.000Z"
        store = Store.objects.create(household=self.household, name="Rewe", location="")
        existing = ShoppingItem.objects.create(household=self.household, name="Brot", added_by=self.other)
        milk, session = str(uuid.uuid4()), str(uuid.uuid4())
        batch = [
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "start_session", "client_id": session,
             "store_id": store.pk, "store_name": "Rewe", "store_location": ""},
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "add", "client_id": milk, "name": "Milch", "quantity": ""},
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "update", "item": {"client_id": milk}, "quantity": "2 l"},
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "set_bought", "item": {"id": existing.pk}, "is_bought": True},
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "set_bought", "item": {"client_id": milk}, "is_bought": True},
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "delete",
             "items": [{"id": existing.pk}, {"client_id": milk}]},
            {"op_id": str(uuid.uuid4()), "created_at": now, "type": "end_session", "session": {"client_id": session}},
        ]
        body = {"household_id": self.household.pk, "ops": batch}
        first = self.client.post("/api/shopping/sync/", body, format="json")
        self.assertEqual([r["status"] for r in first.data["results"]], ["ok"] * 7)
        self.assertEqual(first.data["items"], [])
        self.assertIsNone(first.data["session"])
        orders = dict(StoreItemOrder.objects.filter(store=store).values_list("item_name", "avg_position"))
        self.assertEqual(orders, {"brot": 1, "milch": 2})

        # Antwort ging verloren → die App schickt denselben Batch noch einmal.
        again = self.client.post("/api/shopping/sync/", body, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertNotIn("error", [r["status"] for r in again.data["results"]])
        self.assertFalse(ShoppingItem.objects.exists())
        self.assertEqual(ShoppingSession.objects.count(), 1)
        self.assertIn("Milch", again.data["suggestions"])

    def test_session_with_store_created_offline(self):
        response = self.client.post("/api/shopping/sync/", {"household_id": self.household.pk, "ops": [
            {"op_id": "a", "created_at": "x", "type": "start_session", "client_id": str(uuid.uuid4()),
             "store_id": None, "store_name": "Wochenmarkt", "store_location": "Rathausplatz"},
        ]}, format="json")
        self.assertEqual(response.data["results"][0]["status"], "ok")
        self.assertEqual(response.data["session"]["store"]["location"], "Rathausplatz")
        self.assertEqual(response.data["stores"][0]["item_order"], {})
