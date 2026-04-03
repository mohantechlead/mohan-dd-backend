from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0040_reset_orderitem_id_sequence"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoice",
            name="bank",
            field=models.TextField(blank=True, null=True),
        ),
    ]
