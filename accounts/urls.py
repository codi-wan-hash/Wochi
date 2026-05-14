from django.urls import path
from django.contrib.auth import views as auth_views
from .views import home, register_view, profile_view

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register"),
    path("accounts/profil/", profile_view, name="profile"),
    # Stubs - implemented in later tasks
    path("accounts/profil/email/", profile_view, name="email_change"),
    path("accounts/profil/email/abbrechen/", profile_view, name="email_cancel"),
    path("accounts/profil/passwort/", auth_views.PasswordChangeView.as_view(), name="password_change"),
]
