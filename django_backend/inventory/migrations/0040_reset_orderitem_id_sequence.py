from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0039_alter_purchaseitem_before_vat"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                SELECT setval(
                    pg_get_serial_sequence('inventory_orderitem', 'id'),
                    COALESCE((SELECT MAX(id) FROM inventory_orderitem), 1),
                    true
                );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
