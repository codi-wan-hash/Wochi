from django.conf import settings
from django.core.checks import Warning, register

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
