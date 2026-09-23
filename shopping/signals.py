from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ShoppingItem
from .services import record_frequent_item


@receiver(post_save, sender=ShoppingItem)
def remember_item_name(sender, instance, created, raw=False, **kwargs):
    """Jeder neu angelegte Artikel landet in den Vorschlägen – egal ob er über
    Web, API, Offline-Sync oder aus einem Rezept kommt."""
    if created and not raw:
        record_frequent_item(instance.household, instance.name)
