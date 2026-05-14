from django.urls import path
from django.contrib.auth import views as auth_views
from .views import (
    home,
    register_view,
    profile_view,
    email_change_view,
    email_verify_view,
    email_cancel_view,
)

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register"),
    path("accounts/profil/", profile_view, name="profile"),
    path("accounts/profil/email/", email_change_view, name="email_change"),
    path("accounts/profil/email/bestaetigen/<uuid:token>/", email_verify_view, name="email_verify"),
    path("accounts/profil/email/abbrechen/", email_cancel_view, name="email_cancel"),
    path("accounts/profil/passwort/",
         auth_views.PasswordChangeView.as_view(
             template_name="accounts/password_change_form.html",
             success_url="/accounts/profil/passwort/erfolg/",
         ),
         name="password_change"),
    path("accounts/profil/passwort/erfolg/",
         auth_views.PasswordChangeDoneView.as_view(
             template_name="accounts/password_change_done.html",
         ),
         name="password_change_done"),
]
