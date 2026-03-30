# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_role_logistics_store"),
    ]

    operations = [
        migrations.AddField(
            model_name="partner",
            name="contact_person",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="partner",
            name="comments",
            field=models.TextField(blank=True, null=True),
        ),
    ]
