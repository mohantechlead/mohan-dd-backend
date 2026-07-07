from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_receivedpayment"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendorpayment",
            name="insurance",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
