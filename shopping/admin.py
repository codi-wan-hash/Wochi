from django.contrib import admin
from .models import ShoppingItem

@admin.register(ShoppingItem)
class ShoppingItemAdmin(admin.ModelAdmin):
    list_display = ("name", "quantity", "category", "is_bought", "household", "added_by")
    list_filter = ("category", "is_bought", "household")
    search_fields = ("name", "quantity")