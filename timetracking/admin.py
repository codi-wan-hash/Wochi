from django.contrib import admin
from .models import Job, UserProfile, WorkEntry


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "weekly_target_hours", "work_start_date"]
    list_filter = ["user"]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timetracking_enabled", "bundesland", "active_job"]


@admin.register(WorkEntry)
class WorkEntryAdmin(admin.ModelAdmin):
    list_display = ["user", "job", "date", "entry_type", "start_time", "end_time", "break_minutes"]
    list_filter = ["entry_type", "job", "user"]
