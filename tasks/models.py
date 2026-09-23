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
    # SET_NULL statt CASCADE: löscht jemand sein Konto, bleiben seine
    # Aufgaben für den restlichen Haushalt erhalten.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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

    def toggle(self, user=None):
        """Offen <-> erledigt umschalten (Web und API nutzen dieselbe Logik)."""
        return self.set_status("done" if self.status == "open" else "open", user)

    def set_status(self, status, user=None):
        """Status setzen. Wird eine wiederkehrende Aufgabe erledigt, entsteht
        die nächste Aufgabe. Gibt diese Folgeaufgabe zurück (sonst None)."""
        was_open = self.status == "open"
        self.status = status
        self.save(update_fields=["status"])
        if was_open and status == "done":
            return self.create_next_occurrence(user)
        return None

    def create_next_occurrence(self, user=None):
        """Folgeaufgabe anlegen – aber nur einmal.

        Wer eine erledigte Aufgabe versehentlich wieder öffnet und erneut
        abhakt, soll keine zweite Folgeaufgabe bekommen.
        """
        next_due = self.next_due_date()
        if not next_due:
            return None
        existing = Task.objects.filter(
            household=self.household,
            title=self.title,
            recurrence=self.recurrence,
            due_date=next_due,
        ).first()
        if existing:
            return existing
        new_task = Task.objects.create(
            household=self.household,
            title=self.title,
            description=self.description,
            due_date=next_due,
            priority=self.priority,
            recurrence=self.recurrence,
            created_by=user or self.created_by,
        )
        new_task.assigned_to.set(self.assigned_to.all())
        return new_task


