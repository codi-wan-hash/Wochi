from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class UsernameOrEmailBackend(ModelBackend):
    """Anmeldung mit Benutzername oder E-Mail-Adresse.

    Handys schreiben das erste Zeichen oft groß („Anna" statt „anna"), und
    viele wissen nach Monaten nur noch ihre E-Mail-Adresse. Reihenfolge:
    exakter Benutzername, dann Benutzername ohne Groß-/Kleinschreibung, dann
    E-Mail – jeweils nur, wenn der Treffer eindeutig ist.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()

        user = self._unique(User.objects.filter(username=username))
        if user is None:
            user = self._unique(User.objects.filter(username__iexact=username))
        if user is None and "@" in username:
            user = self._unique(User.objects.filter(email__iexact=username))

        if user is None:
            # Gleich viel Arbeit wie bei einem echten Passwortvergleich, damit
            # die Antwortzeit nicht verrät, ob es das Konto gibt.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _unique(queryset):
        matches = list(queryset[:2])
        return matches[0] if len(matches) == 1 else None
