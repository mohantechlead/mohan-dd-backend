from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0037_shippinginvoiceitem_hscode"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="item_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
