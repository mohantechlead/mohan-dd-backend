"""Drop vessel/route values that were scraped from navigation copy.

Older browser scrapes matched the word "ship" inside "Shipment" and stored
values such as "mentTrack Shipment Now Self-Services Abo" as the vessel name
for BLs on sites that never rendered a real tracking result (ESL, CMA CGM,
CU Lines, Star Liners). Those rows now display nonsense in the UI.
"""
import re

from django.db import migrations

_STOPWORDS = {
    "track",
    "trace",
    "tracking",
    "shipment",
    "shipments",
    "shipping",
    "ship",
    "schedule",
    "schedules",
    "status",
    "container",
    "containers",
    "cargo",
    "eta",
    "etd",
    "bl",
    "bill",
    "lading",
    "import",
    "export",
    "service",
    "services",
    "route",
    "routing",
    "destination",
    "origin",
    "port",
    "ports",
    "vessel",
    "voyage",
    "terminal",
    "booking",
    "reference",
    "number",
    "details",
    "search",
    "menu",
    "home",
    "login",
    "register",
}


def _looks_like_vessel(name) -> bool:
    if not isinstance(name, str):
        return False
    cleaned = re.sub(r"[^A-Za-z0-9 .'\-]", " ", name).strip(" .'-")
    if not (2 <= len(cleaned) <= 40):
        return False
    words = [w for w in re.split(r"\s+", cleaned) if w]
    if not words or len(words) > 5:
        return False
    return not any(w.lower() in _STOPWORDS for w in words)


def clean_details(apps, schema_editor):
    BillOfLading = apps.get_model("inventory", "BillOfLading")
    for bl in BillOfLading.objects.iterator():
        changed: list[str] = []
        details = bl.tracking_details if isinstance(bl.tracking_details, dict) else None
        if details:
            updated = dict(details)
            if updated.get("vessel_name") and not _looks_like_vessel(
                updated["vessel_name"]
            ):
                updated.pop("vessel_name", None)
                updated.pop("vessel_voyage", None)
            if updated != details:
                bl.tracking_details = updated
                changed.append("tracking_details")
        if (bl.vessel_name or "").strip() and not _looks_like_vessel(bl.vessel_name):
            bl.vessel_name = None
            changed.append("vessel_name")
        if changed:
            bl.save(update_fields=changed)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0075_clear_noise_status_detail"),
    ]

    operations = [
        migrations.RunPython(clean_details, noop),
    ]
