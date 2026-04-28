from django.conf import settings
from django.db import models


class PushToken(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_token")
    token = models.CharField(max_length=300)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} – {self.token[:30]}"
