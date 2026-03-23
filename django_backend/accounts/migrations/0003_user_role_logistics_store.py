# Generated migration: viewer -> logistics, add store role

from django.db import migrations, models


def migrate_viewer_to_logistics(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="viewer").update(role="logistics")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_partner_id_alter_partner_partnerid"),
    ]

    operations = [
        migrations.RunPython(migrate_viewer_to_logistics, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("sales", "Sales"),
                    ("purchasing", "Purchasing"),
                    ("inventory", "Inventory"),
                    ("logistics", "Logistics"),
                    ("store", "Store"),
                ],
                default="logistics",
                max_length=20,
            ),
        ),
    ]
