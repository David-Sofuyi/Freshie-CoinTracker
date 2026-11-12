from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from market.models import PriceSnapshot


class Command(BaseCommand):
    help = "Delete price snapshots older than N days (default 7)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        deleted, _ = PriceSnapshot.objects.filter(captured_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} snapshots older than {opts['days']} days"))
