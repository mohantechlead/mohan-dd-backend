# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0016_purchase_status_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='shippinginvoiceitem',
            name='grade',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='shippinginvoiceitem',
            name='brand',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
