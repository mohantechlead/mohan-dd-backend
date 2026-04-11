from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0047_fix_grn_dn_date_manual_save"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grn",
            name="total_quantity",
            field=models.FloatField(default=0),
        ),
        migrations.AlterField(
            model_name="grnitems",
            name="quantity",
            field=models.FloatField(),
        ),
        migrations.AlterField(
            model_name="dnitems",
            name="quantity",
            field=models.FloatField(),
        ),
    ]
