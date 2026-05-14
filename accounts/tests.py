import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.core import mail

User = get_user_model()


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
