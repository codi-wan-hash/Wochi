from django.core.cache import cache
from django.utils.http import url_has_allowed_host_and_scheme

from wochi.ratelimit import allow

# Anmeldung: nach zehn Fehlversuchen in 15 Minuten (je IP-Adresse und
# Benutzername) wird das Passwort gar nicht mehr geprüft.
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 15 * 60


def client_ip(request):
    """IP-Adresse des Aufrufers hinter genau einem Reverse-Proxy.

    Der Proxy hängt die Adresse, von der die Anfrage kam, hinten an
    X-Forwarded-For an. Alles davor kann der Client selbst mitschicken – der
    erste Eintrag taugt deshalb nicht für Sperren (jede Anfrage bekäme sonst
    mit einer ausgedachten Adresse ein frisches Kontingent).
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.META.get("REMOTE_ADDR", "")


def safe_next_url(request):
    """Weiterleitungsziel aus ?next= (oder dem Formular), nur wenn es auf diese
    Seite zeigt – sonst "". Verhindert Weiterleitungen auf fremde Seiten."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ""


def _login_key(request, username):
    return f"{client_ip(request)}:{(username or '').strip().lower()}"


def login_blocked(request, username):
    return bool(cache.get(f"login-blocked:{_login_key(request, username)}"))


def record_failed_login(request, username):
    """Fehlversuch zählen; nach dem zehnten ist die Anmeldung 15 Minuten gesperrt.

    allow() meldet erst den Versuch *über* seinem Limit. Mit Limit
    LOGIN_MAX_FAILURES - 1 ist das genau der zehnte Fehlversuch – ab dem
    elften Versuch wird das Passwort dann gar nicht mehr geprüft.
    """
    key = _login_key(request, username)
    if not allow(f"login-failed:{key}", LOGIN_MAX_FAILURES - 1, LOGIN_WINDOW_SECONDS):
        cache.set(f"login-blocked:{key}", True, LOGIN_WINDOW_SECONDS)
