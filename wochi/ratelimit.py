"""Einfache Ratenbegrenzung über den Django-Cache (festes Zeitfenster).

Mit dem Standard-Cache (LocMemCache) zählt jeder gunicorn-Worker für sich –
das ist eine Bremse gegen Missbrauch, kein exaktes Limit. Für ein hartes
Limit bräuchte es einen geteilten Cache (Redis).
"""
from django.core.cache import cache


def allow(key, limit, window_seconds):
    """Zählt einen Versuch für key und gibt zurück, ob er noch im Limit liegt."""
    cache_key = f"ratelimit:{key}"
    if cache.add(cache_key, 1, window_seconds):
        return True
    try:
        count = cache.incr(cache_key)
    except ValueError:
        # Eintrag ist zwischen add() und incr() abgelaufen.
        cache.set(cache_key, 1, window_seconds)
        return True
    return count <= limit
