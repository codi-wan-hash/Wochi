from datetime import timedelta
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

    RECURRENCE_CHOICES = [
        ("none", "Keine"),
        ("weekly", "Wöchentlich"),
        ("monthly", "Monatlich"),
    ]

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    recurrence = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, default="none")
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

    def next_due_date(self):
        if self.recurrence == "weekly":
            return self.due_date + timedelta(weeks=1)
        if self.recurrence == "monthly":
            d = self.due_date
            month = d.month + 1 if d.month < 12 else 1
            year = d.year if d.month < 12 else d.year + 1
            import calendar
            day = min(d.day, calendar.monthrange(year, month)[1])
            return d.replace(year=year, month=month, day=day)
        return None


