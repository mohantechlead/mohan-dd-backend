# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0017_shippinginvoiceitem_grade_brand'),
    ]

    operations = [
        migrations.AddField(
            model_name='shippinginvoice',
            name='sr_no',
            field=models.PositiveIntegerField(default=6),
        ),
    ]
