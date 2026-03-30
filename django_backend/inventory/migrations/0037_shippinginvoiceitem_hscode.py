from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0036_shippinginvoice_extra_totals_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="hscode",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
