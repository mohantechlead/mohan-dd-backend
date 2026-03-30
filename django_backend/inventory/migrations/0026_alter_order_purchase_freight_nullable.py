from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0025_purchaseitem_purchase_number_fk_remaining"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="freight",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="freight",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
