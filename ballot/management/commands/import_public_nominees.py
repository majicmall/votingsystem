import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ballot.models import Category, Nominee, VotingCampaign


class Command(BaseCommand):
    help = "Import a public nominee snapshot into LOCAL SQLite for QA."

    def add_arguments(self, parser):
        parser.add_argument("input", help="Public nominee JSON snapshot.")
        parser.add_argument(
            "--campaign",
            default="atl-hottest-awards",
            help="Local VotingCampaign slug.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes. Without this flag, dry-run only.",
        )

    def handle(self, *args, **options):
        input_path = options["input"]
        campaign_slug = options["campaign"]
        apply_changes = options["apply"]

        engine = settings.DATABASES["default"]["ENGINE"]

        # Critical safety boundary:
        # this importer may NEVER write to PostgreSQL.
        if engine != "django.db.backends.sqlite3":
            raise CommandError(
                "REFUSED: public nominee import is allowed only "
                f"against SQLite. Current engine: {engine}"
            )

        try:
            campaign = VotingCampaign.objects.get(slug=campaign_slug)
        except VotingCampaign.DoesNotExist as exc:
            raise CommandError(
                f"Local campaign not found: {campaign_slug}"
            ) from exc

        with open(input_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

        if payload.get("format") != "atls-hottest-public-nominees-v1":
            raise CommandError("Unsupported or unsafe snapshot format.")

        snapshot_campaign = payload.get("campaign", {}).get("slug")

        if snapshot_campaign != campaign_slug:
            raise CommandError(
                "Campaign mismatch: "
                f"snapshot={snapshot_campaign!r}, "
                f"local={campaign_slug!r}"
            )

        category_rows = payload.get("categories", [])
        nominee_rows = payload.get("nominees", [])

        self.stdout.write("")
        self.stdout.write("=== PUBLIC NOMINEE IMPORT ===")
        self.stdout.write(f"Database engine: {engine}")
        self.stdout.write(f"Campaign: {campaign.slug}")
        self.stdout.write(f"Categories in snapshot: {len(category_rows)}")
        self.stdout.write(f"Nominees in snapshot: {len(nominee_rows)}")
        self.stdout.write(
            f"Mode: {'APPLY' if apply_changes else 'DRY RUN'}"
        )

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. No database records were changed."
                )
            )
            self.stdout.write(
                "Re-run with --apply after reviewing the counts."
            )
            return

        with transaction.atomic():
            category_map = {}

            for row in category_rows:
                category, _ = Category.objects.update_or_create(
                    slug=row["slug"],
                    defaults={
                        "name": row["name"],
                        "group": row["group"],
                        "description": row.get("description", ""),
                        "sort_order": row.get("sort_order", 0),
                        "is_active": row.get("is_active", True),
                    },
                )
                category_map[category.slug] = category

            imported_ids = set()

            for row in nominee_rows:
                category_slug = row["category_slug"]

                category = category_map.get(category_slug)

                if category is None:
                    try:
                        category = Category.objects.get(
                            slug=category_slug
                        )
                    except Category.DoesNotExist as exc:
                        raise CommandError(
                            "Missing category for nominee "
                            f"{row['id']}: {category_slug}"
                        ) from exc

                nominee, _ = Nominee.objects.update_or_create(
                    id=row["id"],
                    defaults={
                        "name": row["name"],
                        "campaign": campaign,
                        "category": category,
                        "photo": row.get("photo") or None,
                        "website": row.get("website", ""),
                        "social_link": row.get("social_link", ""),

                        # Never import private identity/contact data.
                        "nominator_name": "",
                        "nominator_email": "",
                        "contact_email": "",

                        "approval_status": (
                            Nominee.APPROVAL_APPROVED
                        ),
                        "is_active": True,
                    },
                )

                imported_ids.add(nominee.id)

            count = Nominee.objects.filter(
                campaign=campaign,
                id__in=imported_ids,
                approval_status=Nominee.APPROVAL_APPROVED,
                is_active=True,
            ).count()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported/updated {count} public nominees."
            )
        )
        self.stdout.write(
            "Private contact/nominator information was not imported."
        )
