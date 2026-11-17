"""Start the guarantee-letter reference series at 001.

The old ``MP/DD/…`` letters keep their references; new letters use
``MPN/DDFT/001/26`` and count up from there.
"""

from django.db import migrations


def reset_sequence(apps, schema_editor):
    DocumentReferenceSequence = apps.get_model(
        "inventory", "DocumentReferenceSequence"
    )
    DocumentReferenceSequence.objects.filter(year=2026).update(last_number=0)


def restore_sequence(apps, schema_editor):
    # Nothing to restore: the allocator only ever moves forward and skips
    # references that are already taken.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0079_remove_transitadvance_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(reset_sequence, restore_sequence),
    ]
