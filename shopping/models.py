from django.conf import settings
from django.db import models
from django.utils import timezone
from households.models import Household

class ShoppingItem(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="shopping_items")
    name = models.CharField(max_length=200)
    quantity = models.CharField(max_length=100, blank=True)
    is_bought = models.BooleanField(default=False)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shopping_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_bought", "name"]

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
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    check_counter = models.IntegerField(default=0)

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