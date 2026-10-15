from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0039_alter_purchaseitem_before_vat"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoice",
            name="bank",
            field=models.TextField(blank=True, null=True),
        ),
    ]
