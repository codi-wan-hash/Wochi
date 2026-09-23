from django import forms
from django.contrib.auth import get_user_model

from .models import Task


class TaskForm(forms.ModelForm):
    due_date = forms.DateField(
        # Deklarierte Felder bekommen das Label nicht aus Meta.labels – ohne
        # eigenes Label stand hier „Due date“.
        label="Fälligkeitsdatum",
        # <input type="date"> versteht nur ISO-Werte. Ohne format schreibt
        # Django „23.09.2026“ hinein und das Feld bleibt beim Bearbeiten leer.
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
    )

    class Meta:
        model = Task
        fields = ["title", "description", "due_date", "priority", "recurrence", "assigned_to"]
        labels = {
            "title": "Titel",
            "description": "Beschreibung",
            "priority": "Priorität",
            "recurrence": "Wiederholung",
            "assigned_to": "Zugewiesen an",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "recurrence": forms.Select(attrs={"class": "form-select"}),
            "assigned_to": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        household = kwargs.pop("household", None)
        super().__init__(*args, **kwargs)

        # Zur Auswahl stehen nur Mitglieder des eigenen Haushalts. Ohne
        # Haushalt niemand – sonst stünden hier alle Benutzer der Seite.
        if household:
            self.fields["assigned_to"].queryset = household.members.order_by("username")
        else:
            self.fields["assigned_to"].queryset = get_user_model().objects.none()
