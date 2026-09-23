"""Offline-Synchronisation der Einkaufsliste (POST /api/shopping/sync/).

Im Supermarkt hat die App oft kein Netz. Sie wendet jede Änderung sofort lokal
an und legt sie zusätzlich in eine Warteschlange, die sie gesammelt schickt,
sobald wieder Verbindung besteht. Damit ein erneutes Senden (Antwort ging
verloren, Timeout, App wurde beendet) nichts doppelt anlegt oder umkehrt, ist
jede Operation idempotent:

- add: die App vergibt eine client_id (UUID); existiert sie schon, passiert nichts.
- set_bought: setzt den Zustand absolut, statt umzuschalten.
- update/delete: fehlt der Artikel inzwischen, wird die Operation übersprungen.
- start_session: ebenfalls über eine client_id abgesichert.
- end_session: beendet nur genau die angegebene Session, nie eine später
  gestartete.

Jede Operation läuft in einer eigenen Transaktion. Eine ungültige Operation
wird als "error" gemeldet und blockiert die übrigen nicht – die App verwirft
sie dann, statt sie endlos erneut zu senden.
"""
import logging
import operator
import uuid
from functools import reduce

from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import ShoppingItem, ShoppingSession, Store, StoreItemOrder
from .services import active_session, frequent_item_names, item_key, set_bought
from .utils import sort_by_store

logger = logging.getLogger(__name__)

MAX_OPS_PER_REQUEST = 200
MAX_REFS_PER_DELETE = 500

OK = "ok"
SKIPPED = "skipped"
ERROR = "error"


class OpError(Exception):
    """Ungültige Operation – wird der App als status "error" gemeldet."""


def _uuid(value, field="client_id"):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise OpError(f"{field} ist keine gültige UUID.")


def _int(value, field):
    if isinstance(value, bool):
        raise OpError(f"{field} ist ungültig.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise OpError(f"{field} ist ungültig.")


def _text(value, field, max_length, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise OpError(f"{field} muss Text sein.")
    value = value.strip()
    if required and not value:
        raise OpError(f"{field} darf nicht leer sein.")
    if len(value) > max_length:
        raise OpError(f"{field} ist zu lang (max. {max_length} Zeichen).")
    return value


def _ref_filter(ref, what):
    """Q-Objekt für eine Referenz {"id": ..., "client_id": ...}.

    Die App schickt die Server-ID, sobald sie sie kennt, und immer die
    client_id von Einträgen, die sie selbst angelegt hat.
    """
    if not isinstance(ref, dict):
        raise OpError(f"Ungültige {what}-Referenz.")
    conditions = []
    if ref.get("id") is not None:
        conditions.append(Q(pk=_int(ref["id"], f"{what}-ID")))
    if ref.get("client_id"):
        conditions.append(Q(client_id=_uuid(ref["client_id"])))
    if not conditions:
        raise OpError(f"{what}-Referenz ohne id und client_id.")
    return reduce(operator.or_, conditions)


def _find_item(household, ref):
    return ShoppingItem.objects.filter(_ref_filter(ref, "Artikel"), household=household).first()


def _op_add(household, user, op, summary):
    client_id = _uuid(op.get("client_id"))
    name = _text(op.get("name"), "Name", 200, required=True)
    quantity = _text(op.get("quantity"), "Menge", 100)
    if ShoppingItem.objects.filter(household=household, client_id=client_id).exists():
        return OK  # kam schon beim letzten Sendeversuch an
    try:
        with transaction.atomic():
            ShoppingItem.objects.create(
                household=household, name=name, quantity=quantity,
                added_by=user, client_id=client_id,
            )
    except IntegrityError:
        return OK  # paralleler Sendeversuch mit derselben client_id
    summary["added"].append(name)
    return OK


def _op_update(household, user, op, summary):
    item = _find_item(household, op.get("item"))
    if item is None:
        return SKIPPED
    fields = []
    if "name" in op:
        item.name = _text(op["name"], "Name", 200, required=True)
        fields.append("name")
    if "quantity" in op:
        item.quantity = _text(op["quantity"], "Menge", 100)
        fields.append("quantity")
    if fields:
        item.save(update_fields=fields)
    return OK


def _op_set_bought(household, user, op, summary):
    is_bought = op.get("is_bought")
    if not isinstance(is_bought, bool):
        raise OpError("is_bought muss true oder false sein.")
    item = _find_item(household, op.get("item"))
    if item is None:
        return SKIPPED
    set_bought(household, item, is_bought)
    return OK


def _op_delete(household, user, op, summary):
    refs = op.get("items")
    if refs is None and "item" in op:
        refs = [op["item"]]
    if not isinstance(refs, list) or not refs or len(refs) > MAX_REFS_PER_DELETE:
        raise OpError(f"items muss eine Liste mit 1 bis {MAX_REFS_PER_DELETE} Einträgen sein.")
    query = reduce(operator.or_, [_ref_filter(ref, "Artikel") for ref in refs])
    deleted, _ = ShoppingItem.objects.filter(query, household=household).delete()
    return OK if deleted else SKIPPED


def _op_start_session(household, user, op, summary):
    client_id = _uuid(op.get("client_id"))
    if ShoppingSession.objects.filter(household=household, client_id=client_id).exists():
        return OK
    if active_session(household):
        # Jemand anderes kauft schon ein – dessen Einkauf gilt, die App
        # übernimmt ihn mit dem nächsten Stand.
        return SKIPPED

    store = None
    if op.get("store_id") is not None:
        store = Store.objects.filter(
            household=household, pk=_int(op["store_id"], "store_id")
        ).first()
    if store is None:
        if not op.get("store_name"):
            raise OpError("Supermarkt nicht gefunden.")
        name = _text(op.get("store_name"), "Supermarkt", 200, required=True)
        location = _text(op.get("store_location"), "Ort", 200)
        store, _ = Store.objects.get_or_create(household=household, name=name, location=location)

    try:
        with transaction.atomic():
            ShoppingSession.objects.create(
                household=household, store=store, started_by=user, client_id=client_id,
            )
    except IntegrityError:
        pass
    return OK


def _op_end_session(household, user, op, summary):
    session = ShoppingSession.objects.filter(
        _ref_filter(op.get("session"), "Session"),
        household=household, ended_at__isnull=True,
    ).first()
    if session is None:
        return SKIPPED
    session.end()
    return OK


HANDLERS = {
    "add": _op_add,
    "update": _op_update,
    "set_bought": _op_set_bought,
    "delete": _op_delete,
    "start_session": _op_start_session,
    "end_session": _op_end_session,
}


def apply_ops(household, user, ops):
    """Wendet die Operationen der Reihe nach an.

    Gibt (results, summary) zurück: results enthält pro Operation
    {"op_id", "status", ["detail"]}, summary["added"] die Namen neu angelegter
    Artikel (für eine gebündelte Push-Benachrichtigung).
    """
    results = []
    summary = {"added": []}
    for op in ops:
        op_id = op.get("op_id") if isinstance(op, dict) else None
        result = {"op_id": op_id if isinstance(op_id, str) else None}
        try:
            if not isinstance(op, dict):
                raise OpError("Operation muss ein Objekt sein.")
            handler = HANDLERS.get(op.get("type"))
            if handler is None:
                raise OpError("Unbekannter Operationstyp.")
            with transaction.atomic():
                result["status"] = handler(household, user, op, summary)
        except OpError as exc:
            result.update(status=ERROR, detail=str(exc))
        except Exception:
            logger.exception("Sync-Operation fehlgeschlagen")
            result.update(status=ERROR, detail="Interner Fehler.")
        results.append(result)
    return results, summary


def snapshot(household):
    """Aktueller Stand der Liste, so wie die App ihn offline braucht.

    Enthält neben Artikeln und laufender Session auch die gelernte
    Laden-Reihenfolge der offenen Artikel pro Supermarkt – damit kann die App
    die Liste sortieren, auch wenn der Einkauf erst im Laden ohne Netz
    gestartet wird.
    """
    items = list(ShoppingItem.objects.filter(household=household).select_related("added_by"))
    session = active_session(household)
    open_items = [i for i in items if not i.is_bought]
    bought = [i for i in items if i.is_bought]
    if session:
        open_items = sort_by_store(open_items, session.store)

    stores = list(Store.objects.filter(household=household))
    open_keys = {item_key(i.name) for i in open_items}
    orders = {}
    if open_keys and stores:
        for order in StoreItemOrder.objects.filter(
            store__household=household, item_name__in=open_keys
        ):
            orders.setdefault(order.store_id, {})[order.item_name] = order.avg_position

    return {
        "items": open_items + bought,
        "session": session,
        "stores": [(store, orders.get(store.pk, {})) for store in stores],
        "suggestions": frequent_item_names(household),
    }
