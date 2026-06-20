from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0058_orderitem_country_of_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="grn",
            name="is_last",
            field=models.BooleanField(default=False),
        ),
    ]
