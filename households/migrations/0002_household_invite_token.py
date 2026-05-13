import uuid
from django.db import migrations, models


def populate_unique_tokens(apps, schema_editor):
    Household = apps.get_model('households', 'Household')
    for household in Household.objects.all():
        household.invite_token = uuid.uuid4()
        household.save(update_fields=['invite_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('households', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='household',
            name='invite_token',
            field=models.UUIDField(null=True),
        ),
        migrations.RunPython(populate_unique_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='household',
            name='invite_token',
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
    ]
