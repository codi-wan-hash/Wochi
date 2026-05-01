from django import forms
from .models import Task


class TaskForm(forms.ModelForm):
    due_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form_control"})
    )

    class Meta:
        model = Task
        fields = ["title", "description", "due_date", "priority", "recurrence", "assigned_to"]
        labels = {
            "title": "Titel",
            "description": "Beschreibung",
            "due_date": "Fälligkeitsdatum",
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

        if household:
            self.fields["assigned_to"].queryset = household.members.all()
