from django import forms
from .models import Job, UserProfile, WorkEntry


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ["name", "weekly_target_hours", "work_start_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "weekly_target_hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.5"}),
            "work_start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
        }
        labels = {
            "name": "Bezeichnung",
            "weekly_target_hours": "Wochensoll (Stunden)",
            "work_start_date": "Startdatum für Saldo",
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["timetracking_enabled", "bundesland", "daily_target_hours", "work_start_date"]
        widgets = {
            "bundesland": forms.Select(attrs={"class": "form-select"}),
            "daily_target_hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.5"}),
            "work_start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "timetracking_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "timetracking_enabled": "Arbeitszeiterfassung aktivieren",
            "bundesland": "Bundesland (für Feiertage)",
            "daily_target_hours": "Tagessoll (Stunden)",
            "work_start_date": "Startdatum für Saldo",
        }


class WorkEntryForm(forms.ModelForm):
    class Meta:
        model = WorkEntry
        fields = ["job", "date", "entry_type", "start_time", "end_time", "break_minutes"]
        widgets = {
            "job": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "entry_type": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "break_minutes": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }
        labels = {
            "job": "Job",
            "date": "Datum",
            "entry_type": "Typ",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
            "break_minutes": "Pause (Minuten)",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["job"].queryset = Job.objects.filter(user=user)

    def clean(self):
        cleaned_data = super().clean()
        entry_type = cleaned_data.get("entry_type")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if entry_type == "work":
            if not start_time:
                self.add_error("start_time", "Startzeit ist erforderlich.")
            if not end_time:
                self.add_error("end_time", "Endzeit ist erforderlich.")
            if start_time and end_time and end_time <= start_time:
                self.add_error("end_time", "Endzeit muss nach der Startzeit liegen.")
        else:
            cleaned_data["start_time"] = None
            cleaned_data["end_time"] = None
            cleaned_data["break_minutes"] = 0
        return cleaned_data
