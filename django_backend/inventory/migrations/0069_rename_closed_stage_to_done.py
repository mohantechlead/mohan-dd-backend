from django.db import migrations


def forwards(apps, schema_editor):
    Purchase = apps.get_model("inventory", "Purchase")
    Purchase.objects.filter(stage="closed").update(stage="done")


def backwards(apps, schema_editor):
    Purchase = apps.get_model("inventory", "Purchase")
    Purchase.objects.filter(stage="done").update(stage="closed")


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0068_purchase_ecd_file_original_name_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
