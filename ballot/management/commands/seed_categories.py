# ballot/management/commands/seed_categories.py
from django.core.management.base import BaseCommand

from ballot.models import BallotSettings, Category


CATEGORIES = [
    ("ATL’s Hottest Artist of the Year", "music", 10),
    ("ATL’s Hottest Male Artist", "music", 20),
    ("ATL’s Hottest Female Artist", "music", 30),
    ("ATL’s Hottest Group", "music", 40),
    ("ATL’s Hottest DJ", "music", 50),
    ("ATL’s Hottest Producer", "music", 60),
    ("ATL’s Hottest Song", "music", 70),
    ("ATL’s Hottest Music Video", "music", 80),

    ("ATL’s Hottest Actor", "entertainment", 10),
    ("ATL’s Hottest Actress", "entertainment", 20),
    ("ATL’s Hottest Film", "entertainment", 30),

    ("ATL’s Hottest Podcast", "media", 10),
    ("ATL’s Hottest Radio Personality", "media", 20),
    ("ATL’s Hottest Media Platform", "media", 30),

    ("ATL’s Hottest Restaurant", "food", 10),
    ("ATL’s Hottest Food Truck", "food", 20),
    ("ATL’s Hottest Chef", "food", 30),

    ("ATL’s Hottest Clothing Brand", "fashion", 10),
    ("ATL’s Hottest Model", "fashion", 20),

    ("ATL’s Hottest Barber", "beauty", 10),
    ("ATL’s Hottest Hairstylist", "beauty", 20),
    ("ATL’s Hottest Makeup Artist", "beauty", 30),

    ("ATL’s Hottest Entrepreneur", "business", 10),
    ("ATL’s Hottest Small Business", "business", 20),

    ("ATL’s Hottest Nonprofit", "community", 10),
    ("ATL’s Hottest Community Leader", "community", 20),

    ("ATL’s Hottest Athlete", "sports", 10),
    ("ATL’s Hottest Sports Team", "sports", 20),
]


OLD_TO_NEW = {
    "Artist of the Year": "ATL’s Hottest Artist of the Year",
    "Best Male Artist": "ATL’s Hottest Male Artist",
    "Best Female Artist": "ATL’s Hottest Female Artist",
    "Best Group": "ATL’s Hottest Group",
    "Best DJ": "ATL’s Hottest DJ",
    "Best Producer": "ATL’s Hottest Producer",
    "Best Song": "ATL’s Hottest Song",
    "Best Music Video": "ATL’s Hottest Music Video",

    "Best Actor": "ATL’s Hottest Actor",
    "Best Actress": "ATL’s Hottest Actress",
    "Best Film": "ATL’s Hottest Film",

    "Best Podcast": "ATL’s Hottest Podcast",
    "Best Radio Personality": "ATL’s Hottest Radio Personality",
    "Best Media Platform": "ATL’s Hottest Media Platform",

    "Best Restaurant": "ATL’s Hottest Restaurant",
    "Best Food Truck": "ATL’s Hottest Food Truck",
    "Best Chef": "ATL’s Hottest Chef",

    "Best Clothing Brand": "ATL’s Hottest Clothing Brand",
    "Best Model": "ATL’s Hottest Model",

    "Best Barber": "ATL’s Hottest Barber",
    "Best Hairstylist": "ATL’s Hottest Hairstylist",
    "Best Makeup Artist": "ATL’s Hottest Makeup Artist",

    "Best Entrepreneur": "ATL’s Hottest Entrepreneur",
    "Best Small Business": "ATL’s Hottest Small Business",

    "Best Nonprofit": "ATL’s Hottest Nonprofit",
    "Community Leader Award": "ATL’s Hottest Community Leader",

    "Best Athlete": "ATL’s Hottest Athlete",
    "Best Sports Team": "ATL’s Hottest Sports Team",
}


class Command(BaseCommand):
    help = "Seed starter ATL's Hottest ballot categories."

    def handle(self, *args, **options):
        BallotSettings.get_solo()

        renamed = 0
        created = 0
        updated = 0

        for old_name, new_name in OLD_TO_NEW.items():
            old = Category.objects.filter(name=old_name).first()
            existing_new = Category.objects.filter(name=new_name).first()

            if old and not existing_new:
                old.name = new_name
                old.slug = ""
                old.save()
                renamed += 1
            elif old and existing_new:
                old.is_active = False
                old.save(update_fields=["is_active"])
                renamed += 1

        for name, group, sort_order in CATEGORIES:
            obj, was_created = Category.objects.update_or_create(
                name=name,
                defaults={
                    "group": group,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

            if not obj.slug:
                obj.save()

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Categories ready. Renamed: {renamed}. Created: {created}. Updated: {updated}."
            )
        )
