from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0008_seed_weekday_hours"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="job",
            name="weekly_target_hours",
        ),
    ]
