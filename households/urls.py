from django.urls import path
from . import views

urlpatterns = [
    path("choose/", views.choose_household, name="choose_household"),
    path("join/<uuid:token>/", views.join_via_link, name="join_via_link"),
]