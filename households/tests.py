from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from shopping.models import ShoppingItem
from tasks.models import Task
from .models import Household, HouseholdSelection
from .utils import get_current_household, set_current_household

User = get_user_model()


class HouseholdJoinTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="neuling", password="pw123456")
        self.client.login(username="neuling", password="pw123456")

    def _join(self, token):
        return self.client.post("/households/choose/", {"action": "join", "invite_token": token})

    def test_create_shows_success_message(self):
        response = self.client.post(
            "/households/choose/", {"action": "create", "name": "WG Hauptstraße"}, follow=True
        )
        self.assertTrue(self.user.households.filter(name="WG Hauptstraße").exists())
        self.assertContains(response, "wurde erstellt")

    def test_create_sets_current_household(self):
        self.client.post("/households/choose/", {"action": "create", "name": "WG Hauptstraße"})
        self.assertEqual(get_current_household(self.user).name, "WG Hauptstraße")

    def test_create_rejects_blank_and_too_long_names(self):
        for name, error in (
            ("   ", "Bitte gib einen Namen ein."),
            ("x" * 101, "höchstens 100 Zeichen"),
        ):
            with self.subTest(name=name):
                response = self.client.post("/households/choose/", {"action": "create", "name": name})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, error)
        self.assertFalse(Household.objects.exists())

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
        self.assertEqual(get_current_household(self.user), household)

    def test_join_with_pasted_link_or_message(self):
        """Viele fügen den ganzen Link ein – oder gleich die ganze Nachricht."""
        household = Household.objects.create(name="Familie")
        pasted = (
            f"Komm in unseren Haushalt „Familie“ bei Wochii: "
            f"https://wochii.de/households/join/{str(household.invite_token).upper()}/"
        )
        response = self._join(pasted)
        self.assertRedirects(response, "/tasks/", fetch_redirect_response=False)
        self.assertTrue(self.user.households.filter(pk=household.pk).exists())

    def test_invalid_token_shows_error(self):
        response = self._join("11111111-1111-1111-1111-111111111111")
        self.assertContains(response, "Ungültiger oder abgelaufener Einladungslink")
        self.assertFalse(self.user.households.exists())

    def test_garbage_input_shows_error_instead_of_500(self):
        """Household.objects.get(invite_token="kein-token") warf früher einen
        ValidationError und damit einen Serverfehler."""
        for garbage in ("kein-token", "https://wochii.de/households/join/123/", "   "):
            with self.subTest(garbage=garbage):
                response = self._join(garbage)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["join_form"].errors)
        self.assertFalse(self.user.households.exists())

    def test_join_form_label_is_linked(self):
        response = self.client.get("/households/choose/")
        self.assertContains(response, 'for="id_invite_token"')
        self.assertContains(response, 'for="id_name"')
        self.assertNotContains(response, "Einladungstoken")
        self.assertNotContains(response, "Haushaltsadmin")
        self.assertContains(response, "<title>Haushalt einrichten · Wochii</title>")

    def test_choose_redirects_members_to_manage_page(self):
        household = Household.objects.create(name="Familie")
        household.members.add(self.user)
        response = self.client.get("/households/choose/")
        self.assertRedirects(response, "/households/", fetch_redirect_response=False)

    def test_members_can_still_create_another_household(self):
        household = Household.objects.create(name="Familie")
        household.members.add(self.user)
        self.client.post("/households/choose/", {"action": "create", "name": "WG"})
        self.assertEqual(self.user.households.count(), 2)
        self.assertEqual(get_current_household(self.user).name, "WG")

    def test_join_via_link_requires_login(self):
        household = Household.objects.create(name="Linkhaushalt")
        self.client.logout()
        url = f"/households/join/{household.invite_token}/"
        response = self.client.get(url)
        self.assertRedirects(
            response, f"/accounts/login/?next={url}", fetch_redirect_response=False
        )

    def test_join_via_link_joins_and_activates(self):
        own = Household.objects.create(name="Eigener")
        own.members.add(self.user)
        target = Household.objects.create(name="Eingeladen")
        url = f"/households/join/{target.invite_token}/"
        self.assertContains(self.client.get(url), "„Eingeladen“")
        response = self.client.post(url)
        self.assertRedirects(response, "/tasks/", fetch_redirect_response=False)
        self.assertTrue(target.members.filter(pk=self.user.pk).exists())
        self.assertEqual(get_current_household(self.user), target)

    def test_join_via_link_as_member_switches_household(self):
        first = Household.objects.create(name="Erster")
        second = Household.objects.create(name="Zweiter")
        first.members.add(self.user)
        second.members.add(self.user)
        set_current_household(self.user, first)
        response = self.client.get(f"/households/join/{second.invite_token}/")
        self.assertRedirects(response, "/tasks/", fetch_redirect_response=False)
        self.assertEqual(get_current_household(self.user), second)


class HouseholdManageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="anna", password="pw123456", email="anna@example.com")
        self.partner = User.objects.create_user(username="bert", password="pw123456", email="bert@example.com")
        self.household = Household.objects.create(name="Familie")
        self.household.members.add(self.user, self.partner)
        self.client.login(username="anna", password="pw123456")

    def _other_household(self, name="Andere", members=()):
        household = Household.objects.create(name=name)
        household.members.add(*members)
        return household

    def test_page_shows_members_invite_link_and_forms(self):
        response = self.client.get("/households/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Haushalt · Wochii</title>")
        self.assertContains(response, "Familie")
        self.assertContains(response, "bert")
        self.assertContains(
            response, f'value="http://testserver/households/join/{self.household.invite_token}/"'
        )
        self.assertContains(response, "data-invite-share")
        self.assertContains(response, "data-invite-copy")
        self.assertContains(response, f'/households/{self.household.pk}/invite/new/')
        self.assertContains(response, 'name="action" value="create"')
        self.assertContains(response, 'name="action" value="join"')
        self.assertContains(response, f'/households/{self.household.pk}/leave/')
        # Entfernen nur für andere, nicht für sich selbst
        self.assertContains(response, f'/members/{self.partner.pk}/remove/')
        self.assertNotContains(response, f'/members/{self.user.pk}/remove/')
        # Adressen anderer Mitglieder gehen niemanden etwas an
        self.assertNotContains(response, "bert@example.com")

    def test_page_without_household_redirects_to_setup(self):
        User.objects.create_user(username="solo", password="pw123456")
        self.client.login(username="solo", password="pw123456")
        response = self.client.get("/households/")
        self.assertRedirects(response, "/households/choose/", fetch_redirect_response=False)

    def test_actions_require_post(self):
        pk = self.household.pk
        for url in (
            f"/households/{pk}/switch/",
            f"/households/{pk}/leave/",
            f"/households/{pk}/invite/new/",
            f"/households/{pk}/members/{self.partner.pk}/remove/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(self.household.members.filter(pk=self.user.pk).exists())

    def test_foreign_household_actions_are_404(self):
        stranger = User.objects.create_user(username="fremd", password="pw123456")
        foreign = self._other_household("Fremd", members=[stranger])
        token = foreign.invite_token
        for url in (
            f"/households/{foreign.pk}/switch/",
            f"/households/{foreign.pk}/leave/",
            f"/households/{foreign.pk}/invite/new/",
            f"/households/{foreign.pk}/members/{stranger.pk}/remove/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.invite_token, token)
        self.assertEqual(list(foreign.members.all()), [stranger])
        self.assertEqual(get_current_household(self.user), self.household)

    def test_remove_member(self):
        set_current_household(self.partner, self.household)
        response = self.client.post(
            f"/households/{self.household.pk}/members/{self.partner.pk}/remove/", follow=True
        )
        self.assertRedirects(response, "/households/")
        self.assertFalse(self.household.members.filter(pk=self.partner.pk).exists())
        self.assertFalse(HouseholdSelection.objects.filter(user=self.partner).exists())
        self.assertIsNone(get_current_household(self.partner))
        self.assertContains(response, "bert wurde aus „Familie“ entfernt")

    def test_cannot_remove_yourself(self):
        response = self.client.post(
            f"/households/{self.household.pk}/members/{self.user.pk}/remove/", follow=True
        )
        self.assertTrue(self.household.members.filter(pk=self.user.pk).exists())
        self.assertContains(response, "Haushalt verlassen")

    def test_remove_non_member_is_404(self):
        stranger = User.objects.create_user(username="fremd", password="pw123456")
        url = f"/households/{self.household.pk}/members/{stranger.pk}/remove/"
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_regenerate_invite_invalidates_old_link(self):
        old = self.household.invite_token
        response = self.client.post(f"/households/{self.household.pk}/invite/new/", follow=True)
        self.assertContains(response, "funktioniert nicht mehr")
        self.household.refresh_from_db()
        self.assertNotEqual(self.household.invite_token, old)
        self.assertEqual(self.client.get(f"/households/join/{old}/").status_code, 404)
        self.assertContains(response, f"/households/join/{self.household.invite_token}/")

    def test_switch_changes_current_household(self):
        second = self._other_household("WG", members=[self.user])
        response = self.client.post(f"/households/{second.pk}/switch/", follow=True)
        self.assertRedirects(response, "/households/")
        self.assertEqual(get_current_household(self.user), second)
        self.assertContains(response, "„WG“ ist jetzt dein aktiver Haushalt")

    def test_other_households_listed_with_member_count(self):
        third = User.objects.create_user(username="carl", password="pw123456")
        self._other_household("WG", members=[self.user, self.partner, third])
        response = self.client.get("/households/")
        self.assertContains(response, "WG")
        self.assertContains(response, "3 Mitglieder")

    def test_leave_shared_household_keeps_it(self):
        response = self.client.post(f"/households/{self.household.pk}/leave/")
        self.assertRedirects(response, "/households/choose/", fetch_redirect_response=False)
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())
        self.assertFalse(self.household.members.filter(pk=self.user.pk).exists())
        self.assertTrue(self.household.members.filter(pk=self.partner.pk).exists())

    def test_leave_with_other_households_returns_to_manage_page(self):
        second = self._other_household("WG", members=[self.user])
        response = self.client.post(f"/households/{self.household.pk}/leave/")
        self.assertRedirects(response, "/households/", fetch_redirect_response=False)
        self.assertEqual(get_current_household(self.user), second)

    def test_last_member_is_warned_and_household_deleted_on_leave(self):
        solo = self._other_household("Nur ich", members=[self.user])
        set_current_household(self.user, solo)
        Task.objects.create(household=solo, title="Steuer", due_date=date(2026, 9, 1))
        ShoppingItem.objects.create(household=solo, name="Brot", added_by=self.user)

        page = self.client.get("/households/")
        self.assertContains(page, "Du bist das einzige Mitglied")
        self.assertContains(page, "endgültig gelöscht")

        response = self.client.post(f"/households/{solo.pk}/leave/", follow=True)
        self.assertFalse(Household.objects.filter(pk=solo.pk).exists())
        self.assertFalse(Task.objects.filter(title="Steuer").exists())
        self.assertFalse(ShoppingItem.objects.filter(name="Brot").exists())
        self.assertContains(response, "mit allen Daten gelöscht")

    def test_shared_household_confirm_does_not_warn_about_deletion(self):
        page = self.client.get("/households/")
        self.assertNotContains(page, "Du bist das einzige Mitglied")

    def test_create_from_manage_page(self):
        response = self.client.post("/households/", {"action": "create", "name": "Ferienhaus"})
        self.assertRedirects(response, "/households/", fetch_redirect_response=False)
        self.assertEqual(get_current_household(self.user).name, "Ferienhaus")
        self.assertTrue(self.household.members.filter(pk=self.user.pk).exists())

    def test_create_errors_are_shown_on_manage_page(self):
        response = self.client.post("/households/", {"action": "create", "name": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "households/manage.html")
        self.assertContains(response, "Bitte gib einen Namen ein.")

    def test_join_from_manage_page(self):
        target = self._other_household("Oma und Opa")
        response = self.client.post(
            "/households/",
            {"action": "join", "invite_token": f"https://wochii.de/households/join/{target.invite_token}/"},
        )
        self.assertRedirects(response, "/households/", fetch_redirect_response=False)
        self.assertTrue(target.members.filter(pk=self.user.pk).exists())
        self.assertEqual(get_current_household(self.user), target)

    def test_join_errors_are_shown_on_manage_page(self):
        response = self.client.post("/households/", {"action": "join", "invite_token": "quatsch"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kein Einladungscode")
