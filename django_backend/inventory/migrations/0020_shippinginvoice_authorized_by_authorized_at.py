# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0019_shippinginvoice_sr_no_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoice",
            name="authorized_by",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoice",
            name="authorized_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
