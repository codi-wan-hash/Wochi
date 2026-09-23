"""Push-Benachrichtigungen über den Expo-Push-Dienst.

Der Versand läuft in einem Hintergrund-Thread: vorher wartete jeder Request
bis zu 5 Sekunden auf exp.host, und die Offline-Synchronisation hätte für
jeden hinzugefügten Artikel einzeln gewartet.
"""
import logging
import threading

import httpx
from django.db import connection

from .models import PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def notify_users(users, title, body):
    tokens = list(PushToken.objects.filter(user__in=users).values_list("token", flat=True))
    send_push(tokens, title, body)


def notify_household(household, exclude_user, title, body):
    notify_users(household.members.exclude(pk=exclude_user.pk), title, body)


def send_push(tokens, title, body):
    messages = [{"to": t, "title": title, "body": body, "sound": "default"} for t in tokens if t]
    if messages:
        threading.Thread(target=deliver, args=(messages,), daemon=True).start()


def deliver(messages):
    """Schickt die Nachrichten und entfernt Tokens deinstallierter Apps."""
    try:
        response = httpx.post(EXPO_PUSH_URL, json=messages, timeout=10)
        tickets = response.json().get("data", [])
    except Exception:
        logger.warning("Push-Versand fehlgeschlagen", exc_info=True)
        return
    stale = [
        message["to"]
        for message, ticket in zip(messages, tickets)
        if isinstance(ticket, dict)
        and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered"
    ]
    if stale:
        try:
            PushToken.objects.filter(token__in=stale).delete()
        finally:
            # Der Thread hat eine eigene DB-Verbindung; nicht offen lassen.
            connection.close()
