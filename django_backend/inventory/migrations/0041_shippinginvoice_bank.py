from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoice",
            name="bank",
            field=models.TextField(blank=True, null=True),
        ),
    ]
