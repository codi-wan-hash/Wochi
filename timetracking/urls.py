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
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/neu/", views.job_create, name="job_create"),
    path("jobs/<int:pk>/bearbeiten/", views.job_edit, name="job_edit"),
    path("jobs/<int:pk>/loeschen/", views.job_delete, name="job_delete"),
    path("jobs/<int:pk>/aktivieren/", views.job_activate, name="job_activate"),
    path("bericht/", views.report_view, name="report_view"),
    path("bericht/pdf/", views.report_pdf, name="report_pdf"),
    path("bericht/email/", views.report_email, name="report_email"),
    # Alte Monats-URL, für Bookmarks erhalten.
    path("bericht/<int:year>/<int:month>/", views.report_month_redirect, name="report_month"),
]
