from django.db import migrations


def reset_serial_sequences(apps, schema_editor):
    """Fix duplicate PK errors when the id sequence lags behind MAX(id)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in ("inventory_grnitems", "inventory_dnitems"):
            cursor.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    true
                );
                """
            )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0041_shippinginvoice_bank"),
    ]

    operations = [
        migrations.RunPython(reset_serial_sequences, migrations.RunPython.noop),
    ]
