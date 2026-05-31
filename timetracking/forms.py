from django import forms
from .models import Job, UserProfile, WorkEntry
from .utils import is_soll_day


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            "name", "work_start_date",
            "monday_hours", "tuesday_hours", "wednesday_hours",
            "thursday_hours", "friday_hours", "saturday_hours", "sunday_hours",
            "holiday_credit_basis",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "work_start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "holiday_credit_basis": forms.Select(attrs={"class": "form-select"}),
            **{
                f: forms.NumberInput(attrs={
                    "class": "form-control weekday-hours-input",
                    "step": "0.25", "min": "0", "max": "24",
                })
                for f in Job._WEEKDAY_FIELDS
            },
        }
        labels = {
            "name": "Bezeichnung",
            "work_start_date": "Startdatum für Saldo",
            "monday_hours": "Montag",
            "tuesday_hours": "Dienstag",
            "wednesday_hours": "Mittwoch",
            "thursday_hours": "Donnerstag",
            "friday_hours": "Freitag",
            "saturday_hours": "Samstag",
            "sunday_hours": "Sonntag",
            "holiday_credit_basis": "Feiertagsentlastung berechnen nach",
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["timetracking_enabled", "bundesland"]
        widgets = {
            "bundesland": forms.Select(attrs={"class": "form-select"}),
            "timetracking_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "timetracking_enabled": "Arbeitszeiterfassung aktivieren",
            "bundesland": "Bundesland (für Feiertage, gilt für alle Jobs)",
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

    def __init__(self, *args, user=None, bundesland=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bundesland = bundesland
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

        job = cleaned_data.get("job")
        entry_date = cleaned_data.get("date")
        if job and entry_date:
            existing = WorkEntry.objects.filter(job=job, date=entry_date)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                self.add_error("date", f'Für „{job.name}“ gibt es bereits einen Eintrag am {entry_date.strftime("%d.%m.%Y")}.')

        if entry_date and self.bundesland and entry_type and entry_type != "work":
            if not is_soll_day(entry_date, self.bundesland):
                self.add_error(
                    "entry_type",
                    "An Wochenenden und Feiertagen sind nur Arbeitseinträge möglich.",
                )
        return cleaned_data
