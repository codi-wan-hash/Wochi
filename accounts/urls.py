from django.urls import path
from .views import home, register_view

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register")
]