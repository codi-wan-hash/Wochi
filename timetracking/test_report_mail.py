from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from timetracking.models import Job, UserProfile

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReportMailLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("zeit", "zeit@example.com", "Sicher!Passwort1")
        job = Job.objects.create(user=self.user, name="Büro", work_start_date=date(2026, 1, 1), monday_hours=8)
        UserProfile.objects.update_or_create(
            user=self.user, defaults={"timetracking_enabled": True, "active_job": job},
        )
        self.client.force_login(self.user)

    def test_report_mails_are_limited_per_hour(self):
        with mock.patch("timetracking.views._render_report_pdf", return_value=b"%PDF-1.4"):
            for _ in range(7):
                self.client.post("/timetracking/bericht/email/?von=2026-09-01&bis=2026-09-23")
        self.assertEqual(len(mail.outbox), 5)
