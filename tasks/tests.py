from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from households.models import Household
from .models import Task

User = get_user_model()


class TaskViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="taskuser", password="pw123456")
        self.client.login(username="taskuser", password="pw123456")
        self.household = Household.objects.create(name="Testhaushalt")
        self.household.members.add(self.user)

    def _create_task(self, title="Spülmaschine ausräumen"):
        return Task.objects.create(
            household=self.household,
            title=title,
            due_date=date(2026, 8, 1),
            created_by=self.user,
        )

    def test_list_renders(self):
        self._create_task()
        response = self.client.get("/tasks/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Spülmaschine ausräumen")

    def test_empty_state_offers_create_link(self):
        response = self.client.get("/tasks/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/tasks/new/")

    def test_create_form_uses_bootstrap_classes(self):
        response = self.client.get("/tasks/new/")
        self.assertEqual(response.status_code, 200)
        # Das Datumsfeld hatte die kaputte Klasse "form_control"
        self.assertNotContains(response, "form_control")
        self.assertNotContains(response, "btn-btn-outline-secondary")

    def test_create_shows_success_message(self):
        response = self.client.post("/tasks/new/", {
            "title": "Müll rausbringen",
            "description": "",
            "due_date": "2026-08-01",
            "priority": "medium",
            "recurrence": "none",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Task.objects.filter(title="Müll rausbringen").exists())
        self.assertContains(response, "wurde erstellt")

    def test_delete_page_shows_task_title(self):
        task = self._create_task()
        response = self.client.get(f"/tasks/{task.pk}/delete/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Spülmaschine ausräumen")
        # Abbrechen-Link muss als Button formatiert sein
        self.assertContains(response, "btn btn-outline-secondary")

    def test_delete_shows_success_message(self):
        task = self._create_task()
        response = self.client.post(f"/tasks/{task.pk}/delete/", follow=True)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())
        self.assertContains(response, "Aufgabe gelöscht")

    def test_other_household_task_is_not_reachable(self):
        stranger = User.objects.create_user(username="fremd", password="pw123456")
        other = Household.objects.create(name="Fremder Haushalt")
        other.members.add(stranger)
        foreign_task = Task.objects.create(
            household=other, title="Geheim", due_date=date(2026, 8, 1), created_by=stranger,
        )
        self.assertEqual(self.client.get(f"/tasks/{foreign_task.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.get(f"/tasks/{foreign_task.pk}/delete/").status_code, 404)
        self.assertNotContains(self.client.get("/tasks/"), "Geheim")

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/tasks/")
        self.assertRedirects(
            response, "/accounts/login/?next=/tasks/", fetch_redirect_response=False
        )
