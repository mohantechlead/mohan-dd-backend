from django.db import migrations, models


def forwards_fill_orderitem_fields(apps, schema_editor):
    OrderItem = apps.get_model("inventory", "OrderItem")
    for row in OrderItem.objects.select_related("order").all():
        row.order_no = row.order.order_number if row.order_id is not None else None
        row.before_vat = row.total_price
        row.save(update_fields=["order_no", "before_vat"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0033_order_pr_before_vat_totals"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="before_vat",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="order_no",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.RunPython(forwards_fill_orderitem_fields, migrations.RunPython.noop),
    ]
