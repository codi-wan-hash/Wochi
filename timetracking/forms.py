from django import forms
from .models import UserProfile, WorkEntry


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
        fields = ["date", "entry_type", "start_time", "end_time", "break_minutes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "entry_type": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "break_minutes": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }
        labels = {
            "date": "Datum",
            "entry_type": "Typ",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
            "break_minutes": "Pause (Minuten)",
        }

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
