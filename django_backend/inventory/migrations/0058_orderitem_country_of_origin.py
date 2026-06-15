from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0057_dn_is_last"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="country_of_origin",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
