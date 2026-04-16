from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0051_shippinginvoice_ecd_no"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="package",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="drums",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
