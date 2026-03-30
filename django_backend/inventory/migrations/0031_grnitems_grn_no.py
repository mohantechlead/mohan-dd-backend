from django.db import migrations, models


def forwards_fill_grn_no(apps, schema_editor):
    GrnItems = apps.get_model("inventory", "GrnItems")
    for row in GrnItems.objects.select_related("grn").all():
        if row.grn_id is not None:
            row.grn_no = row.grn.grn_no
            row.save(update_fields=["grn_no"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0030_grn_store_keeper"),
    ]

    operations = [
        migrations.AddField(
            model_name="grnitems",
            name="grn_no",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(forwards_fill_grn_no, migrations.RunPython.noop),
    ]
