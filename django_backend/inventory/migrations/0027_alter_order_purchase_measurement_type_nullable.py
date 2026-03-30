from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0026_alter_order_purchase_freight_nullable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="measurement_type",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="measurement_type",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
