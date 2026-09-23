from django.urls import path
from . import views

urlpatterns = [
    path("", views.household_manage, name="household_manage"),
    path("choose/", views.choose_household, name="choose_household"),
    path("join/<uuid:token>/", views.join_via_link, name="join_via_link"),
    path("<int:pk>/switch/", views.household_switch, name="household_switch"),
    path("<int:pk>/leave/", views.household_leave, name="household_leave"),
    path("<int:pk>/invite/new/", views.household_regenerate_invite, name="household_regenerate_invite"),
    path(
        "<int:pk>/members/<int:user_id>/remove/",
        views.household_remove_member,
        name="household_remove_member",
    ),
]
