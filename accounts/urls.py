from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from .views import (
    home,
    register_view,
    profile_view,
    email_change_view,
    email_verify_view,
    email_cancel_view,
    PasswordResetThrottledView,
)

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register"),

    # Anmeldung. Der Pfad bleibt /accounts/login/, weil Djangos LOGIN_URL-Default
    # und @login_required darauf zeigen.
    path("accounts/login/",
         auth_views.LoginView.as_view(template_name="registration/login.html"),
         name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),

    # Passwort vergessen
    path("accounts/passwort-vergessen/",
         PasswordResetThrottledView.as_view(
             template_name="registration/password_reset_form.html",
             email_template_name="registration/password_reset_email.txt",
             subject_template_name="registration/password_reset_subject.txt",
             success_url=reverse_lazy("password_reset_done"),
         ),
         name="password_reset"),
    path("accounts/passwort-vergessen/gesendet/",
         auth_views.PasswordResetDoneView.as_view(
             template_name="registration/password_reset_done.html",
         ),
         name="password_reset_done"),
    path("accounts/passwort-neu/<uidb64>/<token>/",
         auth_views.PasswordResetConfirmView.as_view(
             template_name="registration/password_reset_confirm.html",
             success_url=reverse_lazy("password_reset_complete"),
         ),
         name="password_reset_confirm"),
    path("accounts/passwort-neu/fertig/",
         auth_views.PasswordResetCompleteView.as_view(
             template_name="registration/password_reset_complete.html",
         ),
         name="password_reset_complete"),

    # Profil
    path("accounts/profil/", profile_view, name="profile"),
    path("accounts/profil/email/", email_change_view, name="email_change"),
    path("accounts/profil/email/bestaetigen/<uuid:token>/", email_verify_view, name="email_verify"),
    path("accounts/profil/email/abbrechen/", email_cancel_view, name="email_cancel"),
    path("accounts/profil/passwort/",
         auth_views.PasswordChangeView.as_view(
             template_name="accounts/password_change_form.html",
             success_url=reverse_lazy("password_change_done"),
         ),
         name="password_change"),
    path("accounts/profil/passwort/erfolg/",
         auth_views.PasswordChangeDoneView.as_view(
             template_name="accounts/password_change_done.html",
         ),
         name="password_change_done"),
]
