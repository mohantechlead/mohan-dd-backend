from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0055_purchase_remark"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchase",
            name="insurance_chargers",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
