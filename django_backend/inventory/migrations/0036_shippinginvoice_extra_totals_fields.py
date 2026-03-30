from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0035_alter_orderitem_item_id_non_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoice",
            name="final_price",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoice",
            name="freight_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoice",
            name="reference_no",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoice",
            name="total_bags",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoice",
            name="total_gross_weight",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoice",
            name="total_net_weight",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
