from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0031_grnitems_grn_no"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grnitems",
            name="item_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
