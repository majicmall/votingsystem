from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime

from ballot.models import VotingCampaign


class Command(BaseCommand):
    help = "Set ATL's Hottest voting campaign dates and public message."

    def handle(self, *args, **options):
        start = timezone.make_aware(datetime(2026, 10, 4, 0, 0, 0))
        end = timezone.make_aware(datetime(2026, 11, 22, 23, 59, 59))

        campaign, created = VotingCampaign.objects.update_or_create(
            slug="atl-hottest-awards",
            defaults={
                "name": "ATL's Hottest Awards 2026",
                "nominations_enabled": True,
                "voting_enabled": False,
                "campaign_start_date": start,
                "campaign_end_date": end,
                "is_active_campaign": True,
                "public_message": "Voting starts October 4, 2026 and ends November 22, 2026. Until then, you may preview the ballot and nominees.",
            },
        )

        VotingCampaign.objects.exclude(pk=campaign.pk).update(is_active_campaign=False)

        self.stdout.write(self.style.SUCCESS("Voting schedule updated."))
        self.stdout.write(f"Campaign: {campaign.name}")
        self.stdout.write(f"Voting starts: {campaign.campaign_start_date}")
        self.stdout.write(f"Voting ends: {campaign.campaign_end_date}")
        self.stdout.write(f"Voting enabled: {campaign.voting_enabled}")
        self.stdout.write(f"Voting open now: {campaign.is_voting_open}")
