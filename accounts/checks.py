from django.conf import settings
from django.core.checks import Tags, Warning, register

CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


@register()
def email_backend_configured(app_configs, **kwargs):
    """Warnen, wenn in Produktion kein echter Mailversand konfiguriert ist.

    Ohne EMAIL_BACKEND fällt settings.py auf das Console-Backend zurück. Dann
    landen Passwort-Reset, E-Mail-Bestätigung und Arbeitszeitnachweis still im
    Server-Log statt beim Empfänger.

    Bewusst eine Warnung und kein Error: ein Error würde `manage.py migrate`
    abbrechen und damit das Deployment blockieren.
    """
    if settings.DEBUG:
        return []

    problems = []
    if settings.EMAIL_BACKEND == CONSOLE_BACKEND:
        problems.append(Warning(
            "EMAIL_BACKEND ist das Console-Backend, DEBUG ist aus. "
            "E-Mails werden nicht versendet, sondern nur ins Log geschrieben.",
            hint="EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend "
                 "sowie EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD setzen. "
                 "Prüfen mit: python manage.py sendtestemail <adresse>",
            id="accounts.W001",
        ))
    elif settings.EMAIL_BACKEND == SMTP_BACKEND and not settings.EMAIL_HOST:
        problems.append(Warning(
            "EMAIL_BACKEND ist gesetzt, aber EMAIL_HOST ist leer.",
            hint="EMAIL_HOST in der Umgebung setzen, siehe .env.example.",
            id="accounts.W002",
        ))
    return problems


@register(Tags.security)
def secret_key_not_public(app_configs, **kwargs):
    """Warnen, wenn SECRET_KEY ein öffentlich bekannter Wert ist.

    Die Werte aus KNOWN_INSECURE_SECRET_KEYS stehen im Repository, und
    „django-insecure-…“ ist der Platzhalter aus startproject. Mit einem davon
    kann jeder Sitzungs-Cookies und – solange JWT_SIGNING_KEY fehlt – auch
    App-Tokens fälschen und sich damit als beliebiger Benutzer ausgeben.

    Wie die Mail-Prüfung nur eine Warnung: ein Error würde `migrate` und damit
    das Deployment abbrechen.
    """
    if settings.DEBUG:
        return []

    secret_key = settings.SECRET_KEY or ""
    known = getattr(settings, "KNOWN_INSECURE_SECRET_KEYS", ())
    if secret_key in known or secret_key.startswith("django-insecure-"):
        return [Warning(
            "SECRET_KEY ist ein öffentlich bekannter Wert. Damit lassen sich "
            "Sitzungen und App-Tokens fälschen.",
            hint="Einen langen Zufallswert als SECRET_KEY in der Server-Umgebung "
                 "setzen, z. B. aus: python -c \"import secrets; "
                 "print(secrets.token_urlsafe(50))\". Danach müssen sich alle neu anmelden.",
            id="accounts.W003",
        )]
    return []
