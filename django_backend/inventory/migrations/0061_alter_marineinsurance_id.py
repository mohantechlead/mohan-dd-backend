from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0060_marineinsurance'),
    ]

    operations = [
        migrations.AlterField(
            model_name='marineinsurance',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
