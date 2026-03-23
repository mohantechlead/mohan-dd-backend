# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0020_shippinginvoice_authorized_by_authorized_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="country_of_origin",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
