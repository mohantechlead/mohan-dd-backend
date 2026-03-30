from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0034_orderitem_before_vat_order_no"),
    ]

    operations = [
        migrations.AlterField(
            model_name="orderitem",
            name="item_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
