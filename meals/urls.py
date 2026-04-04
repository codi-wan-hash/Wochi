from django.urls import path
from .views import (
    meal_list,
    meal_create,
    meal_update,
    meal_delete,
    recipe_list,
    recipe_create,
    recipe_update,
    recipe_delete,
)

urlpatterns = [
    path("", meal_list, name="meal_list"),
    path("new/", meal_create, name="meal_create"),
    path("<int:pk>/edit/", meal_update, name="meal_update"),
    path("<int:pk>/delete/", meal_delete, name="meal_delete"),

    path("recipes/", recipe_list, name="recipe_list"),
    path("recipes/new/", recipe_create, name="recipe_create"),
    path("recipes/<int:pk>/edit/", recipe_update, name="recipe_update"),
    path("recipes/<int:pk>/delete/", recipe_delete, name="recipe_delete"),
]