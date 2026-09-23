import re

from django import forms

from .models import Household

# Findet den Code auch mitten in einem eingefügten Link oder einer ganzen
# Nachricht („Komm in unseren Haushalt: https://wochii.de/households/join/…/“).
INVITE_CODE_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


class HouseholdCreateForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = ["name"]
        labels = {"name": "Name des Haushalts"}
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "z. B. Familie Müller",
                "autocomplete": "off",
            }),
        }
        # CharField entfernt Leerzeichen am Rand – nur Leerzeichen ergibt
        # damit „leer“ und landet hier statt als namenloser Haushalt.
        error_messages = {
            "name": {
                "required": "Bitte gib einen Namen ein.",
                "max_length": "Der Name darf höchstens %(limit_value)d Zeichen lang sein.",
            },
        }


class HouseholdJoinForm(forms.Form):
    invite_token = forms.CharField(
        label="Einladungslink oder -code",
        # Großzügig: Wer eine ganze Nachricht mit Link einfügt, soll nicht am
        # abgeschnittenen Ende scheitern (maxlength kürzt beim Einfügen still).
        max_length=2000,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "https://wochii.de/households/join/…",
            "autocomplete": "off",
            "autocapitalize": "none",
            "autocorrect": "off",
            "spellcheck": "false",
        }),
        error_messages={"required": "Bitte füge den Einladungslink oder den Code ein."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = None

    def clean_invite_token(self):
        match = INVITE_CODE_RE.search(self.cleaned_data["invite_token"])
        if not match:
            raise forms.ValidationError(
                "Darin steckt kein Einladungscode. Bitte füge den ganzen Einladungslink ein."
            )
        code = match.group(0).lower()
        household = Household.objects.filter(invite_token=code).first()
        if household is None:
            raise forms.ValidationError(
                "Ungültiger oder abgelaufener Einladungslink. Bitte frag nach einem neuen Link."
            )
        self.household = household
        return code
