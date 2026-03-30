from django.db import migrations, models


def forwards_fill_order_totals(apps, schema_editor):
    Order = apps.get_model("inventory", "Order")
    OrderItem = apps.get_model("inventory", "OrderItem")
    for order in Order.objects.all():
        rows = OrderItem.objects.filter(order=order)
        pr_before_vat = sum((row.total_price for row in rows), 0)
        qty_sum = sum((int(row.quantity) for row in rows), 0)
        order.PR_before_VAT = pr_before_vat
        order.total_quantity = qty_sum
        order.remaining = qty_sum
        order.save(update_fields=["PR_before_VAT", "total_quantity", "remaining"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0032_alter_grnitems_item_id_non_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="PR_before_VAT",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="order",
            name="total_quantity",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="order",
            name="remaining",
            field=models.IntegerField(default=0),
        ),
        migrations.RunPython(forwards_fill_order_totals, migrations.RunPython.noop),
    ]
