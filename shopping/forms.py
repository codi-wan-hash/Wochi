from django import forms
from .models import ShoppingItem

class ShoppingItemForm(forms.ModelForm):
    class Meta:
        model = ShoppingItem
        fields = ["name", "quantity"]
        labels = {
            "name": "Name",
            "quantity": "Menge",
        }
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control", "list": "item-suggestions", "autocomplete": "off",
                "placeholder": "z. B. Milch", "enterkeyhint": "done", "autocapitalize": "sentences",
            }),
            "quantity": forms.TextInput(attrs={
                "class": "form-control", "list": "quantity-suggestions", "autocomplete": "off",
                "placeholder": "Menge", "enterkeyhint": "done",
            }),
        }


class StoreForm(forms.Form):
    name = forms.CharField(
        label="Name", max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "z. B. Rewe", "autocomplete": "off"}),
    )
    location = forms.CharField(
        label="Ort", max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "z. B. Musterstadt", "autocomplete": "off"}),
    )
