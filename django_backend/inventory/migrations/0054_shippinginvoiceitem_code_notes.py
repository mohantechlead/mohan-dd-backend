from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0053_reset_purchaseitem_id_sequence"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="code",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="shippinginvoiceitem",
            name="notes",
            field=models.TextField(blank=True, null=True),
        ),
    ]

