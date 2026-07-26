from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from . import checks  # noqa: F401  (registriert den E-Mail-Check)
