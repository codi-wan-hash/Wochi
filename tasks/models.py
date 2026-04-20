from django.db import models
from django.conf import settings
from households.models import Household

class Task(models.Model):
    PRIORITY_CHOICES = [
        ("low", "Niedrig"),
        ("medium", "Mittel"),
        ("high", "Hoch"),
    ]

    STATUS_CHOICES = [
        ("open", "Offen"),
        ("done", "Erledigt"),
    ]

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    assigned_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_tasks"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_tasks"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "-created_at"]

    def __str__(self):
        return self.title


