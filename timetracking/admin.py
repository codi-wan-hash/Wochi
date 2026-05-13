from django.contrib import admin
from .models import UserProfile, WorkEntry


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timetracking_enabled", "bundesland", "daily_target_hours", "work_start_date"]


@admin.register(WorkEntry)
class WorkEntryAdmin(admin.ModelAdmin):
    list_display = ["user", "date", "entry_type", "start_time", "end_time", "break_minutes"]
    list_filter = ["entry_type", "user"]
