from django.contrib.admin.forms import AdminAuthenticationForm
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .utils import login_blocked, record_failed_login

User = get_user_model()

TOO_MANY_LOGIN_ATTEMPTS = (
    "Zu viele fehlgeschlagene Anmeldeversuche. Bitte warte 15 Minuten und "
    "versuche es dann noch einmal – oder setze dein Passwort zurück."
)


class ThrottledLoginMixin:
    """Bremse gegen Passwort-Raten, gemeinsam für App-Login und Admin-Login."""

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        # Ohne Request (keine IP) und ohne vollständige Eingabe gibt es nichts zu zählen.
        if self.request is None or username is None or not password:
            return super().clean()

        # Gesperrt: gar nicht erst prüfen. Die Meldung ist für bestehende und
        # nicht existierende Konten gleich, verrät also nichts.
        if login_blocked(self.request, username):
            raise forms.ValidationError(
                self.error_messages["too_many_attempts"], code="too_many_attempts"
            )
        try:
            return super().clean()
        except forms.ValidationError:
            record_failed_login(self.request, username)
            raise


class LoginForm(ThrottledLoginMixin, AuthenticationForm):
    """Anmeldung mit Benutzername oder E-Mail und Bremse gegen Passwort-Raten."""

    error_messages = {
        **AuthenticationForm.error_messages,
        # Der Django-Standardtext behauptet, auch der Benutzername sei
        # groß-/kleinschreibungsabhängig – das stimmt hier nicht mehr.
        "invalid_login": (
            "Benutzername/E-Mail oder Passwort stimmt nicht. Beim Passwort "
            "zählt die Groß- und Kleinschreibung."
        ),
        "too_many_attempts": TOO_MANY_LOGIN_ATTEMPTS,
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        username = self.fields["username"]
        username.label = "Benutzername oder E-Mail"
        # E-Mail-Adressen dürfen länger sein als Benutzernamen (150).
        username.max_length = 254
        username.widget.attrs.update({
            "class": "form-control",
            "maxlength": 254,
            "autocorrect": "off",
            "spellcheck": "false",
        })
        self.fields["password"].label = "Passwort"
        self.fields["password"].widget.attrs.update({"class": "form-control"})

class AdminLoginForm(ThrottledLoginMixin, AdminAuthenticationForm):
    """Admin-Anmeldung mit derselben Bremse wie die normale Anmeldung."""

    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "too_many_attempts": TOO_MANY_LOGIN_ATTEMPTS,
    }


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        label="E-Mail",
        required=True,
        # Deklarierte Felder bekommen kein Widget aus Meta.widgets – ohne
        # eigenes Widget fehlte hier die Bootstrap-Klasse.
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )

    # Von UserCreationForm.Meta erben: dort macht field_classes den
    # Benutzernamen zum UsernameField (autocapitalize="none"). Ohne schreiben
    # Handys den ersten Buchstaben groß und es entsteht „Anna“ statt „anna“.
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email"]
        labels = {"username": "Benutzername"}
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "form-control",
                "autocorrect": "off",
                "spellcheck": "false",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
            })
        # „Passwort wiederholen“ erklärt sich selbst; ohne Hilfetext verweist
        # das Feld auch nicht per aria-describedby auf ein fehlendes Element.
        self.fields["password2"].help_text = ""

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        # Wie in der App-API: „Anna“ und „anna“ als zwei Konten führen beim
        # Anmelden (Groß-/Kleinschreibung egal) zu Verwechslungen.
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Dieser Benutzername ist schon vergeben.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        # Eindeutig, weil Passwort-Reset und Anmeldung per E-Mail sonst nicht
        # wissen, welches Konto gemeint ist.
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Diese E-Mail-Adresse wird bereits verwendet.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name"]
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "form-control",
                "autocapitalize": "none",
                "autocomplete": "username",
                "autocorrect": "off",
                "spellcheck": "false",
            }),
            "first_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "family-name"}),
        }
        labels = {
            "username": "Benutzername",
            "first_name": "Vorname",
            "last_name": "Nachname",
        }

    def clean_username(self):
        username = self.cleaned_data["username"]
        # Nur bei einer Änderung prüfen: ältere Konten wie „Anna“ neben „anna“
        # sollen weiter Vor- und Nachnamen speichern können.
        if "username" not in self.changed_data:
            return username
        # Dieselbe Regel wie bei der Registrierung, sonst ließe sich „anna“ hier
        # in „Anna“ eines anderen Kontos umbenennen.
        taken = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError("Dieser Benutzername ist schon vergeben.")
        return username


class CurrentPasswordMixin:
    """Aktuelles Passwort abfragen.

    Schützt Aktionen, mit denen sich ein Konto übernehmen oder zerstören
    lässt, vor jemandem, der nur eine offene Sitzung hat (entsperrtes Handy,
    eingeschleustes Skript).
    """

    def clean_password(self):
        password = self.cleaned_data.get("password") or ""
        if not self.user.check_password(password):
            raise forms.ValidationError("Das Passwort stimmt nicht.", code="password_incorrect")
        return password


def _current_password_field():
    return forms.CharField(
        label="Aktuelles Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "current-password"}),
    )


class EmailChangeForm(CurrentPasswordMixin, forms.Form):
    new_email = forms.EmailField(
        label="Neue E-Mail-Adresse",
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )
    password = _current_password_field()

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_new_email(self):
        new_email = self.cleaned_data["new_email"]
        if self.user and new_email.lower() == (self.user.email or "").lower():
            raise forms.ValidationError("Das ist bereits deine aktuelle Adresse.")
        qs = User.objects.filter(email__iexact=new_email)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("Diese Adresse wird bereits verwendet.")
        return new_email


class AccountDeleteForm(CurrentPasswordMixin, forms.Form):
    password = _current_password_field()

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
