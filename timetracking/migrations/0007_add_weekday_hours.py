from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("timetracking", "0006_userprofile_email_token_expires_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="monday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="job",
            name="tuesday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="job",
            name="wednesday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="job",
            name="thursday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="job",
            name="friday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="job",
            name="saturday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="job",
            name="sunday_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
        ),
    ]
