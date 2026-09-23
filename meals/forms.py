from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction

from households.utils import _normalize_unit, parse_quantity
from .models import MealPlan, Recipe, Ingredient
from .utils import find_recipe_by_title


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

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        if household is not None:
            self.instance.household = household

    def clean_title(self):
        # unique_together (household, title) prüft der ModelForm nicht selbst,
        # weil household kein Formularfeld ist – ohne diese Prüfung endete ein
        # doppelter Name in einem IntegrityError (HTTP 500).
        title = self.cleaned_data["title"]
        duplicates = Recipe.objects.filter(household=self.household, title__iexact=title)
        if duplicates.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Es gibt schon ein Gericht mit diesem Namen.")
        return title


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


class IngredientQuantityForm(forms.ModelForm):
    """Menge einer Zutat ändern.

    Standardmäßig ändert sich nur diese eine Menge. Alle anderen Mengen im
    gleichen Verhältnis umzurechnen ist eine bewusste Zusatzoption (scale_all) –
    vorher wurden bei jeder Korrektur still alle Zutaten mit umgerechnet.
    """

    scale_all = forms.BooleanField(required=False)

    class Meta:
        model = Ingredient
        fields = ["quantity"]
        labels = {"quantity": "Menge"}

    def clean(self):
        cleaned_data = super().clean()
        # Faktor für die übrigen Zutaten; None = nur diese Menge ändern.
        self.factor = None
        if cleaned_data.get("scale_all") and "quantity" in cleaned_data:
            # self.instance enthält hier noch die bisherige Menge.
            self.factor = self._scale_factor(self.instance.quantity, cleaned_data["quantity"])
        return cleaned_data

    @staticmethod
    def _scale_factor(old_quantity, new_quantity):
        old = parse_quantity(old_quantity or "")
        new = parse_quantity(new_quantity or "")
        if not old or not new:
            raise forms.ValidationError(
                "Zum Umrechnen brauchen bisherige und neue Menge eine Zahl, z. B. 200 g → 300 g."
            )
        if old[0] <= 0 or new[0] <= 0:
            raise forms.ValidationError("Zum Umrechnen muss die Menge größer als 0 sein.")
        if _normalize_unit(old[1]) != _normalize_unit(new[1]):
            raise forms.ValidationError("Zum Umrechnen muss die Einheit gleich bleiben.")
        return new[0] / old[0]


class MealPlanForm(forms.ModelForm):
    date = forms.DateField(
        label="Datum",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")
    )
    # Freitext statt Auswahlliste: "Reste" oder "Pizza bestellen" sollen sich
    # planen lassen, ohne vorher ein Gericht anzulegen.
    recipe_title = forms.CharField(
        label="Gericht",
        max_length=200,
        help_text="Ein vorhandenes Gericht auswählen oder einfach einen neuen Namen eintippen.",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "list": "recipe-titles",
            "autocomplete": "off",
            "placeholder": "z. B. Spaghetti Bolognese, Reste, Pizza bestellen",
        }),
    )

    field_order = ["date", "meal_type", "recipe_title", "assigned_to"]

    class Meta:
        model = MealPlan
        fields = ["date", "meal_type", "assigned_to"]
        labels = {
            "meal_type": "Mahlzeit",
            "assigned_to": "Wer kocht?",
        }
        widgets = {
            "meal_type": forms.Select(attrs={"class": "form-select"}),
            "assigned_to": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, household=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self.user = user
        self.created_recipe = False
        if household is not None:
            self.instance.household = household

        # Nur Mitglieder des eigenen Haushalts – ohne Haushalt niemand.
        members = household.members.all() if household is not None else get_user_model().objects.none()
        self.fields["assigned_to"].queryset = members
        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].empty_label = "Noch offen"

        if self.instance.pk and self.instance.recipe_id:
            self.fields["recipe_title"].initial = self.instance.recipe.title

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        meal_type = cleaned_data.get("meal_type")
        if date and meal_type:
            # Wie beim Gericht: household ist kein Formularfeld, deshalb prüft
            # der ModelForm unique_together nicht selbst.
            taken = MealPlan.objects.filter(household=self.household, date=date, meal_type=meal_type)
            if taken.exclude(pk=self.instance.pk).exists():
                label = dict(MealPlan.MEAL_TYPE_CHOICES).get(meal_type, meal_type)
                self.add_error("date", f"Für diesen Tag ist schon ein {label} geplant.")
        return cleaned_data

    def save(self, commit=True):
        """Speichert die Mahlzeit und legt ein unbekanntes Gericht dabei an.

        Das Anlegen passiert erst hier – also nach allen Prüfungen –, damit ein
        abgelehntes Formular kein verwaistes Gericht hinterlässt. Speichert
        deshalb immer (commit=False wird nicht unterstützt).
        """
        meal = super().save(commit=False)
        title = self.cleaned_data["recipe_title"]
        with transaction.atomic():
            recipe = find_recipe_by_title(self.household, title)
            if recipe is None:
                recipe = Recipe.objects.create(
                    household=self.household,
                    title=title,
                    created_by=self.user,
                )
                self.created_recipe = True
            meal.recipe = recipe
            meal.save()
        return meal
