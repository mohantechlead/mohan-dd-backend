from django.db import migrations, models


def forwards_before_vat(apps, schema_editor):
    PurchaseItem = apps.get_model("inventory", "PurchaseItem")
    for pi in PurchaseItem.objects.all():
        pi.before_vat = pi.total_price
        pi.save(update_fields=["before_vat"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0027_alter_order_purchase_measurement_type_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseitem",
            name="before_vat",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="hscode",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.RunPython(forwards_before_vat, migrations.RunPython.noop),
    ]
