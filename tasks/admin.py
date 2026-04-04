from django.contrib import admin
from .models import Task

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "due_date", "priority", "status", "assigned_to", "household")
    list_filter = ("status", "priority", "household")
    search_fields = ("title", "description")
