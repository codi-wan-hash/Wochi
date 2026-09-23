import re
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from households.models import Household
from .models import Task
from .views import group_open_tasks

User = get_user_model()


class TaskViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="taskuser", password="pw123456")
        self.client.login(username="taskuser", password="pw123456")
        self.household = Household.objects.create(name="Testhaushalt")
        self.household.members.add(self.user)

    def _create_task(self, title="Spülmaschine ausräumen", **kwargs):
        kwargs.setdefault("due_date", date(2026, 8, 1))
        kwargs.setdefault("created_by", self.user)
        return Task.objects.create(household=self.household, title=title, **kwargs)

    def _post_data(self, **overrides):
        data = {
            "title": "Müll rausbringen",
            "description": "",
            "due_date": "2026-08-01",
            "priority": "medium",
            "recurrence": "none",
        }
        data.update(overrides)
        return data

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
        response = self.client.post("/tasks/new/", self._post_data(), follow=True)
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

    def test_ajax_delete_returns_json(self):
        task = self._create_task()
        response = self.client.post(
            f"/tasks/{task.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.json()["deleted"], True)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_other_household_task_is_not_reachable(self):
        stranger = User.objects.create_user(username="fremd", password="pw123456")
        other = Household.objects.create(name="Fremder Haushalt")
        other.members.add(stranger)
        foreign_task = Task.objects.create(
            household=other, title="Geheim", due_date=date(2026, 8, 1), created_by=stranger,
        )
        self.assertEqual(self.client.get(f"/tasks/{foreign_task.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.get(f"/tasks/{foreign_task.pk}/delete/").status_code, 404)
        self.assertEqual(self.client.post(f"/tasks/{foreign_task.pk}/toggle/").status_code, 404)
        self.assertNotContains(self.client.get("/tasks/"), "Geheim")
        foreign_task.refresh_from_db()
        self.assertEqual(foreign_task.status, "open")

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/tasks/")
        self.assertRedirects(
            response, "/accounts/login/?next=/tasks/", fetch_redirect_response=False
        )

    def test_list_script_hooks_are_data_attributes(self):
        """Das Seitenskript hängt an data-Attributen statt an Layout-Klassen –
        früher überschrieb es bei wiederkehrenden Aufgaben die Zeile
        „Wiederholung“, weil es die letzte Listenzeile für den Status hielt."""
        task = self._create_task(recurrence="weekly")
        response = self.client.get("/tasks/")
        self.assertContains(response, f'data-task-id="{task.pk}"')
        self.assertContains(response, "<li data-task-status>")
        self.assertContains(response, "data-task-status-label")
        # Erledigen ist ein POST-Formular (funktioniert auch ohne Skript)
        self.assertContains(
            response, f'<form method="post" action="/tasks/{task.pk}/toggle/" data-task-toggle>'
        )


class TaskCreateAndEditTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="anna", password="pw123456")
        self.partner = User.objects.create_user(username="bert", password="pw123456")
        self.household = Household.objects.create(name="Familie")
        self.household.members.add(self.user, self.partner)
        self.client.login(username="anna", password="pw123456")

    def _post(self, **overrides):
        data = {
            "title": "Fenster putzen",
            "description": "",
            "due_date": "2026-08-01",
            "priority": "medium",
            "recurrence": "none",
        }
        data.update(overrides)
        return self.client.post("/tasks/new/", data)

    def test_create_saves_assignments(self):
        """Regression: form.save(commit=False) ohne save_m2m() verlor die Zuweisungen."""
        response = self._post(assigned_to=[self.user.pk, self.partner.pk])
        self.assertRedirects(response, "/tasks/", fetch_redirect_response=False)
        task = Task.objects.get(title="Fenster putzen")
        self.assertEqual(set(task.assigned_to.all()), {self.user, self.partner})
        self.assertEqual(task.household, self.household)
        self.assertEqual(task.created_by, self.user)

    def test_create_rejects_assignment_to_non_member(self):
        stranger = User.objects.create_user(username="fremd", password="pw123456")
        response = self._post(assigned_to=[stranger.pk])
        self.assertEqual(response.status_code, 200)
        self.assertIn("assigned_to", response.context["form"].errors)
        self.assertFalse(Task.objects.filter(title="Fenster putzen").exists())

    def test_assignee_choices_are_household_members_only(self):
        User.objects.create_user(username="nachbar", password="pw123456")
        response = self.client.get("/tasks/new/")
        choices = response.context["form"].fields["assigned_to"].queryset
        self.assertEqual(set(choices), {self.user, self.partner})

    def test_create_form_defaults_due_date_to_today(self):
        response = self.client.get("/tasks/new/")
        today = timezone.localdate().isoformat()
        self.assertContains(response, f'value="{today}"')

    def test_edit_form_shows_date_in_iso_format(self):
        """<input type="date"> ignoriert „01.08.2026“ – das Feld war beim Bearbeiten leer."""
        task = Task.objects.create(
            household=self.household, title="Rasen", due_date=date(2026, 8, 1), created_by=self.user
        )
        response = self.client.get(f"/tasks/{task.pk}/edit/")
        self.assertContains(response, 'value="2026-08-01"')
        self.assertContains(response, "Fälligkeitsdatum")
        self.assertNotContains(response, "Due date")

    def test_edit_keeps_assignments_editable(self):
        task = Task.objects.create(
            household=self.household, title="Rasen", due_date=date(2026, 8, 1), created_by=self.user
        )
        response = self.client.post(f"/tasks/{task.pk}/edit/", {
            "title": "Rasen mähen",
            "description": "",
            "due_date": "2026-08-02",
            "priority": "low",
            "recurrence": "none",
            "assigned_to": [self.partner.pk],
        })
        self.assertRedirects(response, "/tasks/", fetch_redirect_response=False)
        task.refresh_from_db()
        self.assertEqual(list(task.assigned_to.all()), [self.partner])

    def test_form_titles(self):
        self.assertContains(self.client.get("/tasks/new/"), "<title>Neue Aufgabe · Wochii</title>")


class TaskToggleTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="anna", password="pw123456")
        self.household = Household.objects.create(name="Familie")
        self.household.members.add(self.user)
        self.client.login(username="anna", password="pw123456")

    def _task(self, **kwargs):
        kwargs.setdefault("title", "Müll rausbringen")
        kwargs.setdefault("due_date", date(2026, 9, 22))
        return Task.objects.create(household=self.household, created_by=self.user, **kwargs)

    def _ajax_toggle(self, task):
        return self.client.post(f"/tasks/{task.pk}/toggle/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_get_does_not_change_status(self):
        task = self._task()
        response = self.client.get(f"/tasks/{task.pk}/toggle/")
        self.assertEqual(response.status_code, 405)
        task.refresh_from_db()
        self.assertEqual(task.status, "open")

    def test_post_without_script_redirects_with_message(self):
        task = self._task()
        response = self.client.post(f"/tasks/{task.pk}/toggle/", follow=True)
        self.assertRedirects(response, "/tasks/")
        task.refresh_from_db()
        self.assertEqual(task.status, "done")
        self.assertContains(response, "ist erledigt")

    def test_ajax_toggle_reports_status(self):
        task = self._task()
        data = self._ajax_toggle(task).json()
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["status_display"], "Erledigt")
        self.assertIsNone(data["follow_up"])
        data = self._ajax_toggle(task).json()
        self.assertEqual(data["status"], "open")
        self.assertIn("wieder offen", data["message"])

    def test_recurring_task_creates_follow_up(self):
        task = self._task(recurrence="weekly")
        data = self._ajax_toggle(task).json()
        self.assertIsNotNone(data["follow_up"])
        follow_up = Task.objects.get(pk=data["follow_up"]["id"])
        self.assertEqual(follow_up.household, self.household)
        self.assertEqual(follow_up.status, "open")
        self.assertEqual(follow_up.due_date, date(2026, 9, 29))
        self.assertEqual(data["follow_up"]["due_date"], "2026-09-29")
        self.assertIn("29.09.2026", data["message"])

    def test_recurring_toggle_back_and_forth_creates_one_follow_up(self):
        task = self._task(recurrence="weekly")
        for _ in range(3):  # erledigt → offen → erledigt
            self._ajax_toggle(task)
        follow_ups = Task.objects.filter(title="Müll rausbringen").exclude(pk=task.pk)
        self.assertEqual(follow_ups.count(), 1)

    def test_follow_up_appears_in_list(self):
        task = self._task(recurrence="weekly", due_date=timezone.localdate())
        self._ajax_toggle(task)
        response = self.client.get("/tasks/?fragment=1")
        open_titles = [t.title for group in response.context["groups"] for t in group["tasks"]]
        self.assertEqual(open_titles, ["Müll rausbringen"])
        self.assertEqual([t.pk for t in response.context["done_tasks"]], [task.pk])


class TaskListTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="anna", password="pw123456")
        self.household = Household.objects.create(name="Familie")
        self.household.members.add(self.user)
        self.client.login(username="anna", password="pw123456")
        self.today = timezone.localdate()

    def _task(self, title, due_date, **kwargs):
        kwargs.setdefault("created_by", self.user)
        return Task.objects.create(household=self.household, title=title, due_date=due_date, **kwargs)

    def test_group_open_tasks_by_due_date(self):
        wednesday = date(2026, 9, 23)
        tasks = [
            Task(title="Gestern", due_date=date(2026, 9, 22)),
            Task(title="Heute", due_date=wednesday),
            Task(title="Sonntag", due_date=date(2026, 9, 27)),
            Task(title="Montag", due_date=date(2026, 9, 28)),
        ]
        groups = group_open_tasks(tasks, wednesday)
        self.assertEqual([g["key"] for g in groups], ["overdue", "today", "week", "later"])
        self.assertEqual([g["label"] for g in groups], ["Überfällig", "Heute", "Diese Woche", "Später"])
        self.assertEqual(
            [[t.title for t in g["tasks"]] for g in groups],
            [["Gestern"], ["Heute"], ["Sonntag"], ["Montag"]],
        )

    def test_empty_groups_are_left_out(self):
        groups = group_open_tasks([Task(title="Heute", due_date=date(2026, 9, 23))], date(2026, 9, 23))
        self.assertEqual([g["key"] for g in groups], ["today"])

    def test_open_tasks_come_before_old_done_tasks(self):
        """Früher standen monatealte erledigte Aufgaben (frühes Datum) ganz oben."""
        self._task("Uralt erledigt", date(2025, 1, 1), status="done")
        self._task("Heute fällig", self.today)
        self._task("Längst überfällig", self.today - timedelta(days=5))
        content = self.client.get("/tasks/").content.decode()
        self.assertLess(content.index("Längst überfällig"), content.index("Heute fällig"))
        self.assertLess(content.index("Heute fällig"), content.index("Uralt erledigt"))
        self.assertLess(content.index("Überfällig"), content.index("Längst überfällig"))

    def test_overdue_tasks_are_marked(self):
        self._task("Längst überfällig", self.today - timedelta(days=5))
        response = self.client.get("/tasks/")
        self.assertContains(response, "task-group--overdue")
        self.assertContains(response, "is-overdue")
        self.assertContains(response, "(überfällig)")

    def test_heading_is_not_week_scoped(self):
        response = self.client.get("/tasks/")
        self.assertContains(response, '<h1 class="h2 mb-1">Aufgaben</h1>')
        self.assertNotContains(response, "Wochenaufgaben")
        self.assertContains(response, "<title>Aufgaben · Wochii</title>")

    def test_done_tasks_are_collapsed_by_default(self):
        self._task("Erledigt", self.today, status="done")
        response = self.client.get("/tasks/")
        self.assertContains(response, '<details class="task-done" data-done-tasks>')
        response = self.client.get("/tasks/?status=done")
        self.assertContains(response, '<details class="task-done" data-done-tasks open>')

    def test_done_section_shows_most_recent_30(self):
        for i in range(35):
            self._task(f"Erledigt {i}", date(2026, 1, 1) + timedelta(days=i), status="done")
        response = self.client.get("/tasks/?status=done")
        done = response.context["done_tasks"]
        self.assertEqual(len(done), 30)
        self.assertEqual(done[0].title, "Erledigt 34")
        self.assertEqual(response.context["done_total"], 35)
        self.assertContains(response, "Die letzten 30 von 35")

    def test_status_filter(self):
        self._task("Offene Sache", self.today)
        self._task("Erledigte Sache", self.today, status="done")
        open_only = self.client.get("/tasks/?status=open")
        self.assertContains(open_only, "Offene Sache")
        self.assertNotContains(open_only, "Erledigte Sache")
        done_only = self.client.get("/tasks/?status=done")
        self.assertContains(done_only, "Erledigte Sache")
        self.assertNotContains(done_only, "Offene Sache")

    def test_filter_buttons_show_active_state(self):
        content = self.client.get("/tasks/?status=done").content.decode()

        def button(value):
            match = re.search(rf'<button[^>]*value="{value}"[^>]*>', content)
            self.assertIsNotNone(match, value)
            return match.group(0)

        self.assertIn('aria-pressed="true"', button("done"))
        self.assertRegex(button("done"), r'class="[^"]*\bactive\b')
        for other in ("all", "open"):
            self.assertIn('aria-pressed="false"', button(other))
            self.assertNotRegex(button(other), r'class="[^"]*\bactive\b')

        default = self.client.get("/tasks/?status=unsinn").content.decode()
        self.assertRegex(default, r'<button[^>]*value="all"[^>]*aria-pressed="true"')

    def test_dates_are_german(self):
        self._task("Rasen mähen", date(2026, 8, 1))
        self.assertContains(self.client.get("/tasks/"), "Sa, 01.08.2026")

    def test_missing_creator_is_not_printed_as_none(self):
        self._task("Ohne Ersteller", self.today, created_by=None)
        response = self.client.get("/tasks/")
        self.assertContains(response, "<strong>Angelegt von:</strong> –")
        self.assertNotContains(response, "None")

    def test_query_count_does_not_grow_with_tasks(self):
        partner = User.objects.create_user(username="bert", password="pw123456")
        self.household.members.add(partner)

        def add_tasks(count):
            for i in range(count):
                for status in ("open", "done"):
                    task = self._task(f"{status} {i}", self.today + timedelta(days=i), status=status)
                    task.assigned_to.add(self.user, partner)

        def queries():
            with CaptureQueriesContext(connection) as context:
                self.assertEqual(self.client.get("/tasks/").status_code, 200)
            return len(context.captured_queries)

        add_tasks(1)
        few = queries()
        add_tasks(10)
        self.assertEqual(queries(), few)

    def test_fragment_renders_only_sections(self):
        self._task("Rasen mähen", self.today)
        response = self.client.get("/tasks/?fragment=1")
        self.assertTemplateUsed(response, "tasks/_task_sections.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, "Rasen mähen")

    def test_clear_done_deletes_only_done_tasks_of_current_household(self):
        done = self._task("Erledigt", self.today, status="done")
        still_open = self._task("Offen", self.today)
        other = Household.objects.create(name="Fremd")
        foreign_done = Task.objects.create(
            household=other, title="Fremd erledigt", due_date=self.today, status="done"
        )
        response = self.client.post("/tasks/clear-done/", follow=True)
        self.assertRedirects(response, "/tasks/")
        self.assertFalse(Task.objects.filter(pk=done.pk).exists())
        self.assertTrue(Task.objects.filter(pk=still_open.pk).exists())
        self.assertTrue(Task.objects.filter(pk=foreign_done.pk).exists())
        self.assertContains(response, "1 erledigte Aufgabe gelöscht")

    def test_clear_done_requires_post(self):
        done = self._task("Erledigt", self.today, status="done")
        self.assertEqual(self.client.get("/tasks/clear-done/").status_code, 405)
        self.assertTrue(Task.objects.filter(pk=done.pk).exists())

    def test_clear_done_button_asks_for_confirmation(self):
        self._task("Erledigt", self.today, status="done")
        response = self.client.get("/tasks/")
        self.assertContains(response, 'action="/tasks/clear-done/"')
        self.assertContains(response, "data-confirm=")
