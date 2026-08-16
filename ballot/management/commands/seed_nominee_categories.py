from django.core.management.base import BaseCommand
from django.utils.text import slugify

from ballot.models import Category


OFFICIAL_CATEGORIES = [
    # Entertainment
    ("Hottest Actor TV/Film", "Entertainment"),
    ("Hottest Actress TV/Film", "Entertainment"),
    ("Hottest Actor in Stageplay", "Entertainment"),
    ("Hottest Actress in Stageplay", "Entertainment"),
    ("Hottest Stageplay Production", "Entertainment"),
    ("Hottest Band", "Entertainment"),
    ("Hottest Comedian", "Entertainment"),
    ("Hottest Comedienne", "Entertainment"),
    ("Hottest DJ Male", "Entertainment"),
    ("Hottest DJ Female", "Entertainment"),
    ("Hottest Female Vocalist", "Entertainment"),
    ("Hottest Male Vocalist", "Entertainment"),
    ("Hottest Hip Hop/Rap Male", "Entertainment"),
    ("Hottest Hip Hop/Rap Female", "Entertainment"),
    ("Hottest Musicians", "Entertainment"),
    ("Hottest Music Producer", "Entertainment"),
    ("Hottest Spoken Word Artist", "Entertainment"),
    ("Hottest TV/Film Production", "Entertainment"),

    # Media
    ("Hottest Author", "Media"),
    ("Hottest Media Professional", "Media"),
    ("Hottest Online Radio Show", "Media"),
    ("Hottest Online Radio Personality", "Media"),
    ("Hottest Online TV Show", "Media"),
    ("Hottest Photography", "Media"),
    ("Hottest Video Production", "Media"),

    # Professionals
    ("Hottest Baker", "Professionals"),
    ("Hottest Barber", "Professionals"),
    ("Hottest Bartender", "Professionals"),
    ("Hottest Chef/Caterer", "Professionals"),
    ("Hottest Talent Management", "Professionals"),
    ("Hottest Entrepreneur", "Professionals"),

    # Fashion
    ("Hottest Accessories Designer", "Fashion"),
    ("Hottest Fashion Designer", "Fashion"),
    ("Fashion Stylist", "Fashion"),
    ("Hottest Hairstylist", "Fashion"),
    ("Hottest Female Model", "Fashion"),
    ("Hottest Male Model", "Fashion"),
    ("Hottest Mature Model", "Fashion"),
    ("Hottest Full Figured Model", "Fashion"),
    ("Hottest Make Up Artist", "Fashion"),

    # Community
    ("Hottest Cares", "Community"),
    ("Hottest Public Official", "Community"),

    # Personalities
    ("Hottest Event Host", "Personalities"),
    ("Hottest Inspirational Personality", "Personalities"),
    ("Hottest Rising Superstar", "Personalities"),
    ("Ms ATL's Hottest", "Personalities"),
    ("Hottest Power Couple", "Personalities"),
    ("Gentlemen Of The Year", "Personalities"),

    # Events
    ("Hottest Promotion", "Events"),

    # Venues
    ("Hottest Live Entertainment Spot", "Venues"),
    ("Hottest Social Hangout Spot", "Venues"),
    ("Hottest Event", "Venues"),
    ("Hottest Food Lounge", "Venues"),
    ("Hottest Fine Dining", "Venues"),
    ("Hottest Rooftop Experience", "Venues"),
]


def official_category_slug(name):
    cleaned = name.strip()

    if cleaned.lower().startswith("hottest "):
        cleaned = cleaned[8:]

    cleaned = cleaned.replace("ATL's", "ATLs").replace("ATL’s", "ATLs")
    return f"atlshottest-{slugify(cleaned)}"


def get_model_field_names(model):
    return {field.name for field in model._meta.fields}


def count_related_records(obj):
    total = 0

    for relation in obj._meta.related_objects:
        accessor = relation.get_accessor_name()
        if not accessor:
            continue

        try:
            manager = getattr(obj, accessor)
            if hasattr(manager, "count"):
                total += manager.count()
        except Exception:
            pass

    return total


def move_related_records(source, target):
    """
    Move normal FK reverse relations from source category to target category.
    This protects nominee/category data when duplicate categories exist.
    """
    moved = 0

    for relation in source._meta.related_objects:
        accessor = relation.get_accessor_name()
        if not accessor:
            continue

        # Most expected case: related model has a ForeignKey to Category.
        try:
            related_manager = getattr(source, accessor)
            related_model = relation.related_model
            field_name = relation.field.name

            qs = related_model.objects.filter(**{field_name: source})
            count = qs.count()

            if count:
                qs.update(**{field_name: target})
                moved += count
        except Exception:
            # If Django relation is not a simple FK, leave it alone.
            pass

    return moved


class Command(BaseCommand):
    help = "Seed the official ATL's Hottest nominee categories."

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Safely remove unused old categories and archive protected old categories when possible.",
        )

    def handle(self, *args, **options):
        field_names = get_model_field_names(Category)

        group_field = None
        for candidate in ["group", "category_group", "section", "category_type"]:
            if candidate in field_names:
                group_field = candidate
                break

        order_field = None
        for candidate in ["display_order", "sort_order", "order"]:
            if candidate in field_names:
                order_field = candidate
                break

        active_field = None
        for candidate in ["is_active", "active", "is_public"]:
            if candidate in field_names:
                active_field = candidate
                break

        official_slugs = set()

        self.stdout.write(self.style.WARNING("Seeding official ATL's Hottest nominee categories..."))

        for index, (name, group) in enumerate(OFFICIAL_CATEGORIES, start=1):
            slug = official_category_slug(name)
            official_slugs.add(slug)

            by_name = Category.objects.filter(name=name).first()
            by_slug = Category.objects.filter(slug=slug).first()

            created = False

            if by_name and by_slug and by_name.pk != by_slug.pk:
                # Conflict: one record has the official name, another has the official slug.
                # Keep the slug owner as the official public category and move related records to it.
                moved = move_related_records(by_name, by_slug)

                old_pk = by_name.pk
                by_name.name = f"Archived - Duplicate {old_pk} - {by_name.name}"
                by_name.slug = f"archived-duplicate-{old_pk}-{by_name.slug}"
                if active_field:
                    setattr(by_name, active_field, False)
                by_name.save()

                category = by_slug
                if moved:
                    self.stdout.write(self.style.WARNING(
                        f"Merged {moved} related record(s) into {slug}"
                    ))

            else:
                category = by_slug or by_name

            if category is None:
                category = Category(name=name, slug=slug)
                created = True

            category.name = name
            category.slug = slug

            if group_field:
                setattr(category, group_field, group)

            if order_field:
                setattr(category, order_field, index)

            if active_field:
                setattr(category, active_field, True)

            category.save()

            status = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(
                f"{status}: {category.name} — {group} — {category.slug}"
            ))

        stale_categories = Category.objects.exclude(slug__in=official_slugs)

        if stale_categories.exists():
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Old categories found that are not in the new official list:"))

            for category in stale_categories.order_by("name"):
                related_count = count_related_records(category)
                self.stdout.write(f"- {category.name} ({category.slug}) — related records: {related_count}")

            if options["replace"]:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("Replace mode enabled. Safely cleaning old categories..."))

                for category in stale_categories:
                    related_count = count_related_records(category)

                    if related_count == 0:
                        name = category.name
                        category.delete()
                        self.stdout.write(self.style.SUCCESS(f"Deleted unused old category: {name}"))
                    else:
                        changed = False

                        if active_field:
                            setattr(category, active_field, False)
                            changed = True

                        if not category.name.startswith("Archived - "):
                            category.name = f"Archived - {category.name}"
                            changed = True

                        if changed:
                            category.save()
                            self.stdout.write(self.style.WARNING(f"Archived protected old category: {category.name}"))
                        else:
                            self.stdout.write(self.style.WARNING(f"Kept protected old category: {category.name}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Official nominee category seed complete."))
        self.stdout.write(self.style.SUCCESS(f"Official categories active/created: {len(OFFICIAL_CATEGORIES)}"))

        if not options["replace"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Tip: run with --replace to safely remove unused old categories."))
