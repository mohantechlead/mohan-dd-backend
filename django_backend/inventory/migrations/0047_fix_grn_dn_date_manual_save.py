from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0046_git_table"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grn",
            name="date",
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name="dn",
            name="date",
            field=models.DateField(),
        ),
    ]
