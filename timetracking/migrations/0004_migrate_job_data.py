from django.db import migrations
from decimal import Decimal
from datetime import date as date_type


def migrate_job_data(apps, schema_editor):
    UserProfile = apps.get_model("timetracking", "UserProfile")
    Job = apps.get_model("timetracking", "Job")
    WorkEntry = apps.get_model("timetracking", "WorkEntry")

    for profile in UserProfile.objects.select_related("user").all():
        daily_hours = profile.daily_target_hours or Decimal("8.00")
        weekly_hours = daily_hours * 5
        start_date = profile.work_start_date or date_type.today()

        job, _ = Job.objects.get_or_create(
            user=profile.user,
            name="Hauptjob",
            defaults={
                "weekly_target_hours": weekly_hours,
                "work_start_date": start_date,
            },
        )
        WorkEntry.objects.filter(user=profile.user, job__isnull=True).update(job=job)
        profile.active_job = job
        profile.save(update_fields=["active_job"])


def reverse_migrate_job_data(apps, schema_editor):
    WorkEntry = apps.get_model("timetracking", "WorkEntry")
    WorkEntry.objects.all().update(job=None)


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0003_job_userprofile_active_job_workentry_job"),
    ]

    operations = [
        migrations.RunPython(migrate_job_data, reverse_migrate_job_data),
    ]
