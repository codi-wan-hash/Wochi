from django.urls import path
from . import views

urlpatterns = [
    path("choose/", views.choose_household, name="choose_household"),
]