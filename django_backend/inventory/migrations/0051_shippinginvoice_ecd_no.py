from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0050_purchase_decimal_quantities"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoice",
            name="ecd_no",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
