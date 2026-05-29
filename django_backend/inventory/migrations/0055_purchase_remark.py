from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0054_shippinginvoiceitem_code_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchase",
            name="remark",
            field=models.TextField(blank=True, null=True),
        ),
    ]
