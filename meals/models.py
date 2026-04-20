from django.conf import settings
from django.db import models
from households.models import Household


class Recipe(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="recipes")
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_recipes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]
        unique_together = ("household", "title")

    def __str__(self):
        return self.title


class Ingredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    name = models.CharField(max_length=200)
    quantity = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.name


class MealPlan(models.Model):
    MEAL_TYPE_CHOICES = [
        ("lunch", "Mittagessen"),
        ("dinner", "Abendessen"),
    ]

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="meals")
    date = models.DateField()
    meal_type = models.CharField(max_length=20, choices=MEAL_TYPE_CHOICES)

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="planned_meals"
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "meal_type"]
        unique_together = ("household", "date", "meal_type")

    def __str__(self):
        return f"{self.recipe.title} ({self.date})"