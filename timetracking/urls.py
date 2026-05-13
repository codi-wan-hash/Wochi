from django.urls import path
from . import views

app_name = "timetracking"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("eintrag/neu/", views.entry_create, name="entry_create"),
    path("eintrag/<int:pk>/bearbeiten/", views.entry_edit, name="entry_edit"),
    path("eintrag/<int:pk>/loeschen/", views.entry_delete, name="entry_delete"),
    path("einstellungen/", views.settings_view, name="settings_view"),
    path("monat/<int:year>/<int:month>/", views.month_detail, name="month_detail"),
]
