from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timetracking_enabled", "bundesland", "daily_target_hours", "work_start_date"]
