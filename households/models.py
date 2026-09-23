import uuid

from django.conf import settings
from django.db import models

class Household(models.Model):
    name = models.CharField(max_length=100)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="households",
        blank=True
    )
    invite_token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class HouseholdSelection(models.Model):
    """Welcher Haushalt für einen Benutzer gerade aktiv ist.

    Wer in mehreren Haushalten Mitglied ist (z. B. nach dem Beitritt per
    Einladungslink), kann so zwischen ihnen wechseln. Ohne Eintrag gilt der
    älteste Haushalt, wie bisher.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="household_selection",
    )
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} → {self.household}"
