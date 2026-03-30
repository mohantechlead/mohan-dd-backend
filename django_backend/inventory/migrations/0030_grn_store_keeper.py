from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0029_alter_purchaseitem_item_id_non_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="grn",
            name="store_keeper",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
