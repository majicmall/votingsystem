from django.core.management.base import BaseCommand
from django.utils.text import slugify

from ballot.models import Category


CATEGORIES = [
    ("ATL’s Hottest Barber", "Beauty & Style"),
    ("ATL’s Hottest Beauty Professional", "Beauty & Style"),
    ("ATL’s Hottest Boutique", "Business"),
    ("ATL’s Hottest Business", "Business"),
    ("ATL’s Hottest Chef", "Food & Hospitality"),
    ("ATL’s Hottest Restaurant", "Food & Hospitality"),
    ("ATL’s Hottest Food Truck", "Food & Hospitality"),
    ("ATL’s Hottest DJ", "Entertainment"),
    ("ATL’s Hottest Host", "Entertainment"),
    ("ATL’s Hottest Radio Personality", "Media"),
    ("ATL’s Hottest Podcast", "Media"),
    ("ATL’s Hottest Media Platform", "Media"),
    ("ATL’s Hottest Artist", "Music"),
    ("ATL’s Hottest Rap Artist", "Music"),
    ("ATL’s Hottest R&B Artist", "Music"),
    ("ATL’s Hottest Producer", "Music"),
    ("ATL’s Hottest Video Director", "Film & Creative"),
    ("ATL’s Hottest Photographer", "Film & Creative"),
    ("ATL’s Hottest Videographer", "Film & Creative"),
    ("ATL’s Hottest Event Producer", "Events"),
    ("ATL’s Hottest Promoter", "Events"),
    ("ATL’s Hottest Venue", "Events"),
    ("ATL’s Hottest Influencer", "Creative"),
    ("ATL’s Hottest Content Creator", "Creative"),
    ("ATL’s Hottest Community Organization", "Community"),
    ("ATL’s Hottest Nonprofit", "Community"),
]


class Command(BaseCommand):
    help = "Safely seed ATL's Hottest Awards categories without deleting existing data."

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for index, (name, group) in enumerate(CATEGORIES, start=10):
            slug = slugify(name.replace("’", ""))

            category, was_created = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "group": group,
                    "sort_order": index,
                    "is_active": True,
                },
            )

            changed = False

            if category.name != name:
                category.name = name
                changed = True

            if category.group != group:
                category.group = group
                changed = True

            if category.sort_order in (None, 0):
                category.sort_order = index
                changed = True

            if not category.is_active:
                category.is_active = True
                changed = True

            if was_created:
                created += 1
            elif changed:
                category.save()
                updated += 1

            if was_created:
                self.stdout.write(self.style.SUCCESS(f"Created: {name}"))
            elif changed:
                self.stdout.write(self.style.WARNING(f"Updated: {name}"))
            else:
                self.stdout.write(f"Already exists: {name}")

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created}, updated {updated}."))
