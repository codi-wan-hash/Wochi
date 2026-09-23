from django.urls import path
from .views import (
    task_list,
    task_create,
    task_update,
    task_delete,
    task_toggle_status,
    task_clear_done,
)

urlpatterns = [
    path("", task_list, name="task_list"),
    path("new/", task_create, name="task_create"),
    path("clear-done/", task_clear_done, name="task_clear_done"),
    path("<int:pk>/edit/", task_update, name="task_update"),
    path("<int:pk>/delete/", task_delete, name="task_delete"),
    path("<int:pk>/toggle/", task_toggle_status, name="task_toggle_status"),
]
