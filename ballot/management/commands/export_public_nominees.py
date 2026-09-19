import json

from django.core.management.base import BaseCommand, CommandError

from ballot.models import Nominee, VotingCampaign


class Command(BaseCommand):
    help = "Export public nominee/category data for safe development QA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign",
            default="atl-hottest-awards",
            help="VotingCampaign slug to export.",
        )
        parser.add_argument(
            "--output",
            required=True,
            help="Destination JSON file.",
        )

    def handle(self, *args, **options):
        campaign_slug = options["campaign"]
        output = options["output"]

        try:
            campaign = VotingCampaign.objects.get(slug=campaign_slug)
        except VotingCampaign.DoesNotExist as exc:
            raise CommandError(
                f"Campaign not found: {campaign_slug}"
            ) from exc

        nominees = (
            Nominee.objects
            .filter(
                campaign=campaign,
                is_active=True,
                approval_status=Nominee.APPROVAL_APPROVED,
            )
            .select_related("category")
            .order_by("category__name", "name")
        )

        categories = {}

        nominee_rows = []

        for nominee in nominees:
            category = nominee.category

            categories[category.slug] = {
                "name": category.name,
                "slug": category.slug,
                "group": category.group,
                "description": category.description,
                "sort_order": category.sort_order,
                "is_active": category.is_active,
            }

            nominee_rows.append({
                "id": nominee.id,
                "name": nominee.name,
                "category_slug": category.slug,

                # Public profile fields only.
                "photo": nominee.photo.name if nominee.photo else "",
                "website": nominee.website or "",
                "social_link": nominee.social_link or "",

                "approval_status": nominee.approval_status,
                "is_active": nominee.is_active,
            })

        payload = {
            "format": "atls-hottest-public-nominees-v1",
            "campaign": {
                "name": campaign.name,
                "slug": campaign.slug,
            },
            "categories": sorted(
                categories.values(),
                key=lambda row: (
                    row["group"],
                    row["sort_order"],
                    row["name"],
                ),
            ),
            "nominees": nominee_rows,
        }

        with open(output, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(nominee_rows)} approved active nominees "
                f"and {len(categories)} categories to {output}"
            )
        )

        self.stdout.write(
            "Private nominee/nominator/contact fields were NOT exported."
        )
