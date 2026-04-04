from django.contrib import admin
from .models import MealPlan, Recipe

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("title", "household", "created_by")
    search_fields = ("title", "notes")

@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    list_display = ("recipe", "date", "meal_type", "assigned_to", "household")
    list_filter = ("meal_type", "household")
    search_fields = ("recipe_title",)