"""Gemeinsame Einstellungen für die KI-Funktionen (Web und API).

Jeder Aufruf kostet Geld und blockiert einen Worker, bis OpenAI antwortet.
Deshalb: festes Timeout ohne automatische Wiederholung und ein Tageskontingent
pro Benutzer.
"""
from django.conf import settings
from openai import OpenAI

from wochi.ratelimit import allow

AI_TIMEOUT_SECONDS = 45
AI_TEXT_REQUESTS_PER_DAY = 40
AI_IMAGE_REQUESTS_PER_DAY = 10
QUOTA_MESSAGE = "Tageslimit für KI-Funktionen erreicht. Bitte morgen wieder versuchen."


def openai_client():
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=AI_TIMEOUT_SECONDS,
        max_retries=0,
    )


def ai_quota_available(user, kind="text"):
    """Zählt eine KI-Anfrage des Benutzers; False, wenn das Tageskontingent aufgebraucht ist."""
    limit = AI_IMAGE_REQUESTS_PER_DAY if kind == "image" else AI_TEXT_REQUESTS_PER_DAY
    return allow(f"ai:{kind}:{user.pk}", limit, 24 * 60 * 60)
