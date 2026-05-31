from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0009_remove_weekly_target_hours"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="holiday_credit_basis",
            field=models.CharField(
                choices=[
                    ("per_day", "Nach Tageseingabe"),
                    ("weekly_average", "Wochendurchschnitt"),
                ],
                default="per_day",
                max_length=20,
            ),
        ),
    ]
