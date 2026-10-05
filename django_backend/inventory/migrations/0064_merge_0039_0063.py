# Manual merge migration.
#
# `makemigrations --merge` cannot generate this automatically because the two
# branches share no common ancestor (0041 has intentionally empty
# dependencies after 0040 was removed). This file only joins the heads
# 0039 and 0063 so that `migrate` has a single leaf again. It performs no
# database operations.
#
# NOTE: 0063's AddField operations were already applied out-of-band
# (columns exist); 0063 is recorded in django_migrations, so it is skipped.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0039_alter_purchaseitem_before_vat"),
        ("inventory", "0063_shippinginvoice_destination_contact_name_and_more"),
    ]

    operations = []
