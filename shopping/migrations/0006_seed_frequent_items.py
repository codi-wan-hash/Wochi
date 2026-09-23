from django.db import migrations


def seed_frequent_items(apps, schema_editor):
    """Vorschläge aus den bereits vorhandenen Artikeln übernehmen.

    Sonst hätten bestehende Haushalte nach dem Update leere Vorschläge, sobald
    sie erledigte Artikel von der Liste entfernen.
    """
    ShoppingItem = apps.get_model("shopping", "ShoppingItem")
    FrequentItem = apps.get_model("shopping", "FrequentItem")

    stats = {}
    for household_id, name, created_at in ShoppingItem.objects.values_list(
        "household_id", "name", "created_at"
    ).iterator():
        key = (name or "").strip().lower()[:200]
        if not key:
            continue
        entry = stats.setdefault((household_id, key), {"name": name.strip()[:200], "count": 0, "last": created_at})
        entry["count"] += 1
        if created_at and (entry["last"] is None or created_at > entry["last"]):
            entry["last"] = created_at
            entry["name"] = name.strip()[:200]

    FrequentItem.objects.bulk_create(
        [
            FrequentItem(
                household_id=household_id,
                name=entry["name"],
                name_key=key,
                times_added=entry["count"],
                last_added_at=entry["last"],
            )
            for (household_id, key), entry in stats.items()
        ],
        ignore_conflicts=True,
        batch_size=500,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0005_frequentitem_shoppingitem_client_id_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_frequent_items, migrations.RunPython.noop),
    ]
