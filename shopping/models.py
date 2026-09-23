from django.conf import settings
from django.db import models
from django.utils import timezone
from households.models import Household

class ShoppingItem(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="shopping_items")
    name = models.CharField(max_length=200)
    quantity = models.CharField(max_length=100, blank=True)
    is_bought = models.BooleanField(default=False)
    # SET_NULL statt CASCADE: löscht jemand sein Konto, bleiben die Artikel
    # für den restlichen Haushalt auf der Liste.
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_items"
    )
    # Von der App vergebene UUID. Macht das Anlegen idempotent: schickt die
    # App eine offline gesammelte Änderung nach einem Timeout erneut, entsteht
    # kein Duplikat.
    client_id = models.UUIDField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_bought", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "client_id"], name="unique_shopping_item_client_id"
            ),
        ]

    def __str__(self):
        return self.name


class Store(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("household", "name", "location")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} – {self.location}" if self.location else self.name


class ShoppingSession(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="shopping_sessions")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="sessions")
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    check_counter = models.IntegerField(default=0)
    # Wie ShoppingItem.client_id: ein offline gestarteter Einkauf wird beim
    # erneuten Senden nicht ein zweites Mal angelegt.
    client_id = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "client_id"], name="unique_shopping_session_client_id"
            ),
        ]

    def end(self):
        self.ended_at = timezone.now()
        self.save()

    @property
    def is_active(self):
        return self.ended_at is None


class StoreItemOrder(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="item_orders")
    item_name = models.CharField(max_length=200)  # normalized: lowercase + stripped
    avg_position = models.FloatField(default=0)
    times_seen = models.IntegerField(default=0)

    class Meta:
        unique_together = ("store", "item_name")

    ALPHA = 0.3  # weight for newest shopping trip; higher = adapts faster

    def record(self, position):
        if self.times_seen == 0:
            self.avg_position = position
        else:
            self.avg_position = self.avg_position * (1 - self.ALPHA) + position * self.ALPHA
        self.times_seen += 1
        self.save()


class FrequentItem(models.Model):
    """Was der Haushalt schon einmal auf die Liste gesetzt hat.

    Quelle für die Vorschläge beim Hinzufügen (Web-Autovervollständigung und
    Offline-Vorschläge in der App). Erledigte Artikel können dadurch von der
    Liste gelöscht werden, ohne dass die Vorschläge verloren gehen. Pro
    Haushalt auf FREQUENT_ITEMS_LIMIT Einträge begrenzt (siehe services.py).
    """

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="frequent_items")
    name = models.CharField(max_length=200)
    name_key = models.CharField(max_length=200)  # normalisiert: klein + getrimmt
    times_added = models.PositiveIntegerField(default=0)
    last_added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-times_added", "-last_added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name_key"], name="unique_frequent_item_per_household"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.times_added}×)"
