from django import forms
from .models import MealPlan, Recipe

class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = ["title", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3})
        }

class MealPlanForm(forms.ModelForm):
    date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )

    class Meta:
        model = MealPlan
        fields = ["date", "meal_type", "recipe", "assigned_to"]
        widgets = {
            "meal_type": forms.Select(attrs={"class": "form-select"}),
            "recipe": forms.Select(attrs={"class": "form-select"}),
            "assigned_to": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        household = kwargs.pop("household", None)
        super().__init__(*args, **kwargs)

        if household:
            self.fields["assigned_to"].queryset = household.members.all()
            self.fields["recipe"].queryset = Recipe.objects.filter(household=household)