"""Clear status details that were scraped from page chrome (nav tooltips).

Older checks stored copy such as "title=View bookings, see latest tracking
details, BL status, ETA updates and pending tasks with Manage Bookings." as the
shipment status detail. That text comes from a navigation tooltip, not the
shipment, and made Maersk B/Ls look stuck on "Pending".
"""
import re

from django.db import migrations

_NOISE = re.compile(
    r"pending\s+tasks?|manage\s+bookings?|view\s+bookings?|"
    r"tracking\s+details\s*,\s*bl\s+status",
    re.IGNORECASE,
)


def clear_noise_details(apps, schema_editor):
    BillOfLading = apps.get_model("inventory", "BillOfLading")
    for bl in BillOfLading.objects.exclude(status_detail__isnull=True).iterator():
        if bl.status_detail and _NOISE.search(bl.status_detail):
            bl.status_detail = None
            bl.save(update_fields=["status_detail"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0074_billoflading_tracking_details"),
    ]

    operations = [
        migrations.RunPython(clear_noise_details, noop),
    ]
