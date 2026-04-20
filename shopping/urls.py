from django.urls import path
from .views import (
    shopping_list,
    shopping_create,
    shopping_update,
    shopping_delete,
    shopping_toggle_bought,
    shopping_merge_quantity,
    start_shopping,
    end_shopping,
)

urlpatterns = [
    path("", shopping_list, name="shopping_list"),
    path("new/", shopping_create, name="shopping_create"),
    path("<int:pk>/edit/", shopping_update, name="shopping_update"),
    path("<int:pk>/delete/", shopping_delete, name="shopping_delete"),
    path("<int:pk>/toggle/", shopping_toggle_bought, name="shopping_toggle_bought"),
    path("<int:pk>/merge/", shopping_merge_quantity, name="shopping_merge_quantity"),
    path("start/", start_shopping, name="start_shopping"),
    path("end/", end_shopping, name="end_shopping"),
]
