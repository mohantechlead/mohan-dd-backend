from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0028_purchaseitem_before_vat_hscode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseitem",
            name="item_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
