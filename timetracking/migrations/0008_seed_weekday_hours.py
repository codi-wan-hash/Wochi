from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def seed_weekday_hours(apps, schema_editor):
    Job = apps.get_model("timetracking", "Job")
    for job in Job.objects.all():
        weekly = job.weekly_target_hours or Decimal("0")
        daily = (weekly / Decimal("5")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        job.monday_hours = daily
        job.tuesday_hours = daily
        job.wednesday_hours = daily
        job.thursday_hours = daily
        job.friday_hours = daily
        job.saturday_hours = Decimal("0")
        job.sunday_hours = Decimal("0")
        job.save(update_fields=[
            "monday_hours", "tuesday_hours", "wednesday_hours",
            "thursday_hours", "friday_hours", "saturday_hours", "sunday_hours",
        ])


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0007_add_weekday_hours"),
    ]

    operations = [
        migrations.RunPython(seed_weekday_hours, reverse_seed),
    ]
