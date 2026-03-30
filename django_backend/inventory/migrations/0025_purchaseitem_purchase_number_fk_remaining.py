# PurchaseItem: FK to Purchase.purchase_number (not UUID); per-line remaining (default = quantity).

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F


def forwards_remaining(apps, schema_editor):
    PurchaseItem = apps.get_model("inventory", "PurchaseItem")
    PurchaseItem.objects.all().update(remaining=F("quantity"))


def forwards_copy_fk(apps, schema_editor):
    PurchaseItem = apps.get_model("inventory", "PurchaseItem")
    Purchase = apps.get_model("inventory", "Purchase")
    for pi in PurchaseItem.objects.all():
        p = Purchase.objects.get(pk=pi.purchase_id)
        pi.purchase_by_number = p
        pi.save(update_fields=["purchase_by_number"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0024_purchase_before_vat_totals"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseitem",
            name="remaining",
            field=models.IntegerField(default=0),
        ),
        migrations.RunPython(forwards_remaining, migrations.RunPython.noop),
        migrations.AddField(
            model_name="purchaseitem",
            name="purchase_by_number",
            field=models.ForeignKey(
                db_column="purchase_number",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items_by_number_tmp",
                to="inventory.purchase",
                to_field="purchase_number",
            ),
        ),
        migrations.RunPython(forwards_copy_fk, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="purchaseitem",
            name="purchase",
        ),
        migrations.RenameField(
            model_name="purchaseitem",
            old_name="purchase_by_number",
            new_name="purchase",
        ),
        migrations.AlterField(
            model_name="purchaseitem",
            name="purchase",
            field=models.ForeignKey(
                db_column="purchase_number",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items",
                to="inventory.purchase",
                to_field="purchase_number",
            ),
        ),
    ]
