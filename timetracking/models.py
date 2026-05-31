from datetime import date, datetime
from decimal import Decimal
from django.db import models
from django.conf import settings

HOLIDAY_CREDIT_BASIS_CHOICES = [
    ("per_day", "Nach Tageseingabe"),
    ("weekly_average", "Wochendurchschnitt"),
]

BUNDESLAND_CHOICES = [
    ("BB", "Brandenburg"),
    ("BE", "Berlin"),
    ("BW", "Baden-Württemberg"),
    ("BY", "Bayern"),
    ("HB", "Bremen"),
    ("HE", "Hessen"),
    ("HH", "Hamburg"),
    ("MV", "Mecklenburg-Vorpommern"),
    ("NI", "Niedersachsen"),
    ("NW", "Nordrhein-Westfalen"),
    ("RP", "Rheinland-Pfalz"),
    ("SH", "Schleswig-Holstein"),
    ("SL", "Saarland"),
    ("SN", "Sachsen"),
    ("ST", "Sachsen-Anhalt"),
    ("TH", "Thüringen"),
]


class Job(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    name = models.CharField(max_length=100)
    work_start_date = models.DateField()

    monday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    tuesday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    wednesday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    thursday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    friday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    saturday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    sunday_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))

    holiday_credit_basis = models.CharField(
        max_length=20,
        choices=HOLIDAY_CREDIT_BASIS_CHOICES,
        default="per_day",
    )

    _WEEKDAY_FIELDS = [
        "monday_hours", "tuesday_hours", "wednesday_hours", "thursday_hours",
        "friday_hours", "saturday_hours", "sunday_hours",
    ]

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    def hours_for_weekday(self, weekday: int) -> Decimal:
        return getattr(self, self._WEEKDAY_FIELDS[weekday])

    @property
    def weekly_target_hours(self) -> Decimal:
        return sum((self.hours_for_weekday(i) for i in range(7)), Decimal("0"))

    @property
    def configured_workday_count(self) -> int:
        return sum(1 for f in self._WEEKDAY_FIELDS if getattr(self, f) > 0)

    @property
    def weekly_average_hours(self) -> Decimal:
        n = self.configured_workday_count
        return (self.weekly_target_hours / n) if n else Decimal("0")


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="userprofile",
    )
    timetracking_enabled = models.BooleanField(default=False)
    bundesland = models.CharField(max_length=2, choices=BUNDESLAND_CHOICES, default="BY")
    active_job = models.ForeignKey(
        "Job",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_for_profiles",
    )
    # Legacy fields kept temporarily for data migration — removed in Task 3
    daily_target_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("8.00"))
    work_start_date = models.DateField(null=True, blank=True)
    pending_email = models.EmailField(null=True, blank=True)
    email_verification_token = models.UUIDField(null=True, blank=True, unique=True)
    email_token_expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Profile({self.user.username})"


class WorkEntry(models.Model):
    ENTRY_TYPE_CHOICES = [
        ("work", "Arbeit"),
        ("urlaub", "Urlaub"),
        ("krankheit", "Krankheit"),
        ("homeoffice", "Homeoffice"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="work_entries",
    )
    job = models.ForeignKey(
        "Job",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    date = models.DateField()
    entry_type = models.CharField(max_length=12, choices=ENTRY_TYPE_CHOICES, default="work")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    break_minutes = models.IntegerField(default=0)

    class Meta:
        unique_together = ("job", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.user.username} – {self.date}"

    @property
    def worked_hours(self):
        if self.entry_type != "work" or not self.start_time or not self.end_time:
            return None
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        total_minutes = (end - start).total_seconds() / 60 - self.break_minutes
        return round(total_minutes / 60, 2)
