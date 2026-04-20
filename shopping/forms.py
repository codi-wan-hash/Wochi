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
            "name": forms.TextInput(attrs={"class": "form-control", "list": "item-suggestions", "autocomplete": "off"}),
            "quantity": forms.TextInput(attrs={"class": "form-control", "list": "quantity-suggestions", "autocomplete": "off"}),
        }