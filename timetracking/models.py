from datetime import date, datetime
from decimal import Decimal
from django.db import models
from django.conf import settings

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


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="userprofile",
    )
    timetracking_enabled = models.BooleanField(default=False)
    bundesland = models.CharField(max_length=2, choices=BUNDESLAND_CHOICES, default="BY")
    daily_target_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("8.00"))
    work_start_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Profile({self.user.username})"
