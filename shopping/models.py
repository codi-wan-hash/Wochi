from django.conf import settings
from django.db import models
from households.models import Household

class ShoppingItem(models.Model):
    CATEGORY_CHOICES = [
        ("produce", "Obst & Gemüse"),
        ("dairy", "Milchprodukte"),
        ("meat", "Fleisch"),
        ("dry", "Trockenwaren"),
        ("frozen", "Tiefkühl"),
        ("other", "Sonstiges"),
    ]

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="shopping_items")
    name = models.CharField(max_length=200)
    quantity = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    is_bought = models.BooleanField(default=False)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shopping_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_bought", "category", "name"]

    def __str__(self):
        return self.name