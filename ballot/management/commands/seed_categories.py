# ballot/management/commands/seed_categories.py
from django.core.management.base import BaseCommand

from ballot.models import BallotSettings, Category


CATEGORIES = [
    ("Artist of the Year", "music", 10),
    ("Best Male Artist", "music", 20),
    ("Best Female Artist", "music", 30),
    ("Best Group", "music", 40),
    ("Best DJ", "music", 50),
    ("Best Producer", "music", 60),
    ("Best Song", "music", 70),
    ("Best Music Video", "music", 80),
    ("Best Actor", "entertainment", 10),
    ("Best Actress", "entertainment", 20),
    ("Best Film", "entertainment", 30),
    ("Best Podcast", "media", 10),
    ("Best Radio Personality", "media", 20),
    ("Best Media Platform", "media", 30),
    ("Best Restaurant", "food", 10),
    ("Best Food Truck", "food", 20),
    ("Best Chef", "food", 30),
    ("Best Clothing Brand", "fashion", 10),
    ("Best Model", "fashion", 20),
    ("Best Barber", "beauty", 10),
    ("Best Hairstylist", "beauty", 20),
    ("Best Makeup Artist", "beauty", 30),
    ("Best Entrepreneur", "business", 10),
    ("Best Small Business", "business", 20),
    ("Best Nonprofit", "community", 10),
    ("Community Leader Award", "community", 20),
    ("Best Athlete", "sports", 10),
    ("Best Sports Team", "sports", 20),
]


class Command(BaseCommand):
    help = "Seed starter ATL's Hottest ballot categories."

    def handle(self, *args, **options):
        BallotSettings.get_solo()

        created = 0
        updated = 0

        for name, group, sort_order in CATEGORIES:
            _obj, was_created = Category.objects.update_or_create(
                name=name,
                defaults={
                    "group": group,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Categories ready. Created: {created}. Updated: {updated}.")
        )
