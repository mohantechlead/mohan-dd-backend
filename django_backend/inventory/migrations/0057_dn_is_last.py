from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0056_purchase_insurance_chargers"),
    ]

    operations = [
        migrations.AddField(
            model_name="dn",
            name="is_last",
            field=models.BooleanField(default=False),
        ),
    ]
