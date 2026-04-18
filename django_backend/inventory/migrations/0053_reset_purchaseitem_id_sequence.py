from django.db import migrations


def reset_purchaseitem_id_sequence(apps, schema_editor):
    """Fix duplicate PK on inventory_purchaseitem when the id sequence lags MAX(id)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT setval(
                pg_get_serial_sequence('inventory_purchaseitem', 'id'),
                COALESCE((SELECT MAX(id) FROM inventory_purchaseitem), 1),
                true
            );
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0052_shippinginvoiceitem_package_drums"),
    ]

    operations = [
        migrations.RunPython(
            reset_purchaseitem_id_sequence, migrations.RunPython.noop
        ),
    ]
