# Generated manually

from django.db import migrations, models


def clear_default_sr_no(apps, schema_editor):
    """Set sr_no to NULL for existing rows (they had default 6)."""
    ShippingInvoice = apps.get_model("inventory", "ShippingInvoice")
    ShippingInvoice.objects.all().update(sr_no=None)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0018_shippinginvoice_sr_no'),
    ]

    operations = [
        migrations.AlterField(
            model_name='shippinginvoice',
            name='sr_no',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(clear_default_sr_no, migrations.RunPython.noop),
    ]
