from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0048_grn_dn_decimal_quantity"),
    ]

    operations = [
        migrations.AddField(
            model_name="grn",
            name="remark",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dn",
            name="remark",
            field=models.TextField(blank=True, null=True),
        ),
    ]
