from django.core.management.base import BaseCommand

from inventory.api import _check_and_notify_all_warehouse_expiry


class Command(BaseCommand):
    help = (
        "Scan active warehouse storage notes and email notifications for any that "
        "have reached their storage expiry date. Safe to run on a schedule (cron / "
        "Heroku Scheduler)."
    )

    def handle(self, *args, **options):
        sent = _check_and_notify_all_warehouse_expiry()
        self.stdout.write(
            self.style.SUCCESS(f"Warehouse expiry scan complete. Notifications sent: {sent}")
        )
