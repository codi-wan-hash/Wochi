from django import forms
from .models import MealPlan, Recipe, Ingredient

class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = ["title", "notes", "instructions"]
        labels = {
            "title": "Titel",
            "notes": "Notizen",
            "instructions": "Zubereitung",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "instructions": forms.Textarea(attrs={"class": "form-control", "rows": 8, "placeholder": "Schritt-für-Schritt Zubereitung..."}),
        }

class IngredientForm(forms.ModelForm):
    class Meta:
        model = Ingredient
        fields = ["name", "quantity"]
        labels = {
            "name": "Name",
            "quantity": "Menge",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "z.B. Tomaten", "list": "item-suggestions", "autocomplete": "off"}),
            "quantity": forms.TextInput(attrs={"class": "form-control", "placeholder": "z.B. 400g", "list": "quantity-suggestions", "autocomplete": "off"}),
        }


class MealPlanForm(forms.ModelForm):
    date = forms.DateField(
        label="Datum",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")
    )

    class Meta:
        model = MealPlan
        fields = ["date", "meal_type", "recipe", "assigned_to"]
        labels = {
            "meal_type": "Mahlzeit",
            "recipe": "Gericht",
            "assigned_to": "Zugewiesen an",
        }
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