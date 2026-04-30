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
        # Use IF NOT EXISTS so this is safe to re-run after a partial failure
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE households_household ADD COLUMN IF NOT EXISTS invite_token uuid",
                    reverse_sql="ALTER TABLE households_household DROP COLUMN IF EXISTS invite_token",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='household',
                    name='invite_token',
                    field=models.UUIDField(null=True),
                ),
            ],
        ),
        # Assign a fresh unique UUID to every row (fixes duplicate values from failed run)
        migrations.RunPython(populate_unique_tokens, migrations.RunPython.noop),
        # Set NOT NULL + unique constraint (drop first in case of partial previous attempt)
        migrations.RunSQL(
            sql="""
                ALTER TABLE households_household ALTER COLUMN invite_token SET NOT NULL;
                ALTER TABLE households_household DROP CONSTRAINT IF EXISTS households_household_invite_token_key;
                ALTER TABLE households_household ADD CONSTRAINT households_household_invite_token_key UNIQUE (invite_token);
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Bring Django's model state in line with the final field definition
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name='household',
                    name='invite_token',
                    field=models.UUIDField(default=uuid.uuid4, unique=True),
                ),
            ],
        ),
    ]
