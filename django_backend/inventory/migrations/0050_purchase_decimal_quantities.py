from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0049_grn_dn_remark"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchase",
            name="total_quantity",
            field=models.FloatField(default=0),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="remaining",
            field=models.FloatField(default=0),
        ),
        migrations.AlterField(
            model_name="purchaseitem",
            name="quantity",
            field=models.FloatField(),
        ),
        migrations.AlterField(
            model_name="purchaseitem",
            name="remaining",
            field=models.FloatField(default=0),
        ),
    ]
