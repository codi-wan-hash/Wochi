"""Geschäftslogik der Einkaufsliste.

Gemeinsam genutzt von den Web-Views, der REST-API und der Offline-Synchronisation
der App, damit sich z. B. das Abhaken überall gleich verhält.
"""
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import FrequentItem, ShoppingItem, ShoppingSession, StoreItemOrder

# Obergrenze für gemerkte Artikelnamen pro Haushalt. Darüber werden die am
# längsten nicht mehr benutzten Namen verworfen, damit die Tabelle nicht
# endlos wächst.
FREQUENT_ITEMS_LIMIT = 500


def item_key(name):
    """Normalisierter Name für Vergleiche (Laden-Reihenfolge, Vorschläge)."""
    return (name or "").strip().lower()


def active_session(household):
    return (
        ShoppingSession.objects.filter(household=household, ended_at__isnull=True)
        .select_related("store")
        .first()
    )


def set_bought(household, item, is_bought):
    """Setzt den Gekauft-Status absolut (idempotent) und lernt die Laden-Reihenfolge.

    Läuft gerade ein Einkauf, merkt sich StoreItemOrder, an welcher Stelle der
    Artikel abgehakt wurde. Gibt zurück, ob sich der Status geändert hat.
    """
    if item.is_bought == is_bought:
        return False
    item.is_bought = is_bought
    item.save(update_fields=["is_bought"])
    if is_bought:
        session = active_session(household)
        if session:
            ShoppingSession.objects.filter(pk=session.pk).update(
                check_counter=F("check_counter") + 1
            )
            session.refresh_from_db(fields=["check_counter"])
            order, _ = StoreItemOrder.objects.get_or_create(
                store=session.store, item_name=item_key(item.name)
            )
            order.record(session.check_counter)
    return True


def clear_bought(household):
    """Löscht alle erledigten Artikel des Haushalts. Gibt die Anzahl zurück."""
    deleted, _ = ShoppingItem.objects.filter(household=household, is_bought=True).delete()
    return deleted


def finish_shopping(household):
    """Einkauf beenden: laufende Session schließen, erledigte Artikel entfernen.

    Gibt (session, entfernte_artikel) zurück; session ist None, wenn keiner lief.
    """
    session = active_session(household)
    if session:
        session.end()
    return session, clear_bought(household)


def record_frequent_item(household, name):
    """Zählt einen Artikelnamen für die Vorschläge hoch (oder legt ihn an)."""
    key = item_key(name)
    if not key:
        return
    display = name.strip()[:200]
    now = timezone.now()
    updated = FrequentItem.objects.filter(household=household, name_key=key).update(
        name=display, times_added=F("times_added") + 1, last_added_at=now
    )
    if updated:
        return
    try:
        with transaction.atomic():
            FrequentItem.objects.create(
                household=household, name=display, name_key=key[:200],
                times_added=1, last_added_at=now,
            )
    except IntegrityError:
        # Paralleler Request hat denselben Namen gerade angelegt.
        FrequentItem.objects.filter(household=household, name_key=key).update(
            times_added=F("times_added") + 1, last_added_at=now
        )
        return
    _prune_frequent_items(household)


def _prune_frequent_items(household):
    stale = list(
        FrequentItem.objects.filter(household=household)
        .order_by("-last_added_at", "-pk")
        .values_list("pk", flat=True)[FREQUENT_ITEMS_LIMIT:]
    )
    if stale:
        FrequentItem.objects.filter(pk__in=stale).delete()


def frequent_item_names(household, limit=300):
    """Die häufigsten Artikelnamen des Haushalts, meistgenutzte zuerst."""
    return list(
        FrequentItem.objects.filter(household=household)
        .order_by("-times_added", "-last_added_at")
        .values_list("name", flat=True)[:limit]
    )


def merge_quantity_text(existing, extra):
    """Mengen zusammenführen ("200 g" + "100 g" = "300 g", sonst "a, b").

    Auf die Feldlänge von ShoppingItem.quantity gekürzt – PostgreSQL lehnt
    längere Werte ab, und wiederholtes Zusammenführen kann sie erzeugen.
    """
    from households.utils import merge_quantities

    return merge_quantities(existing or "", (extra or "").strip())[:100]


def add_ingredients(household, user, ingredients):
    """Zutaten auf die Einkaufsliste setzen.

    Steht ein gleichnamiger Artikel schon offen auf der Liste, wird die Menge
    addiert (merge_quantities), sonst ein neuer Artikel angelegt.
    ingredients: Iterable aus (name, menge). Gibt (angelegt, zusammengeführt)
    zurück. Die offene Liste wird nur einmal geladen statt pro Zutat.
    """
    open_items = {}
    for item in ShoppingItem.objects.filter(household=household, is_bought=False).order_by("pk"):
        open_items.setdefault(item_key(item.name), item)

    added = merged = 0
    for name, quantity in ingredients:
        key = item_key(name)
        if not key:
            continue
        existing = open_items.get(key)
        if existing:
            existing.quantity = merge_quantity_text(existing.quantity, quantity)
            existing.save(update_fields=["quantity"])
            merged += 1
        else:
            open_items[key] = ShoppingItem.objects.create(
                household=household,
                name=name.strip()[:200],
                quantity=(quantity or "").strip()[:100],
                added_by=user,
            )
            added += 1
    return added, merged
