from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignSpend,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    BillboardAd,
    advertising_campaign_pacing_snapshot,
    decide_advertising_opportunity_purchase,
)


class AdvertisingCampaignPacingTests(TestCase):

    def aware(self, year, month, day, hour=0, minute=0, second=0):
        return timezone.make_aware(
            datetime(year, month, day, hour, minute, second),
            timezone.get_current_timezone(),
        )

    def setUp(self):
        self.start = self.aware(2026, 10, 1, 0, 0)
        self.end = self.aware(2026, 10, 8, 0, 0)

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="H3B-2A Advertiser",
            campaign_name="Seven Day Pacing Campaign",
            total_budget=Decimal("700.00"),
            minimum_campaign_spend=Decimal("0.00"),
            status=AdvertisingCampaign.STATUS_DRAFT,
            starts_at=self.start,
            ends_at=self.end,
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="H3B-2A Six Second Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            is_active=True,
        )

    def opportunity(self, cost="1.00", available=True, reason="available"):
        return {
            "available": available,
            "reason": reason,
            "appearance_cost": Decimal(cost),
            "placement": BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            "starts_at": self.start + timedelta(days=2),
            "slot_count": 1,
        }

    def create_spend(self, amount):
        AdvertisingCampaignSpend.objects.create(
            campaign=self.campaign,
            creative=self.creative,
            appearance_id=__import__("uuid").uuid4(),
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            slot_count=1,
            locked_slot_price=Decimal(amount),
            media_spend=Decimal(amount),
            platform_share_percent=Decimal("15.000"),
            platform_share_amount=(
                Decimal(amount) * Decimal("0.15")
            ).quantize(Decimal("0.01")),
        )

    def test_two_days_into_seven_day_campaign_targets_200(self):
        moment = self.start + timedelta(days=2)

        snapshot = advertising_campaign_pacing_snapshot(
            campaign=self.campaign,
            moment=moment,
        )

        self.assertEqual(
            snapshot["target_spend"],
            Decimal("200.00"),
        )
        self.assertEqual(
            snapshot["actual_spend"],
            Decimal("0.00"),
        )
        self.assertEqual(
            snapshot["pacing_delta"],
            Decimal("200.00"),
        )
        self.assertEqual(snapshot["pacing_status"], "under")
        self.assertEqual(snapshot["phase"], "active")

    def test_150_spent_against_200_target_is_50_behind(self):
        self.create_spend("150.00")

        snapshot = advertising_campaign_pacing_snapshot(
            campaign=self.campaign,
            moment=self.start + timedelta(days=2),
        )

        self.assertEqual(snapshot["target_spend"], Decimal("200.00"))
        self.assertEqual(snapshot["actual_spend"], Decimal("150.00"))
        self.assertEqual(snapshot["remaining_budget"], Decimal("550.00"))
        self.assertEqual(snapshot["pacing_delta"], Decimal("50.00"))
        self.assertEqual(snapshot["pacing_status"], "under")

    def test_behind_pace_available_opportunity_is_approved(self):
        self.create_spend("150.00")

        decision = decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity("1.26"),
            moment=self.start + timedelta(days=2),
        )

        self.assertTrue(decision["purchase"])
        self.assertEqual(decision["reason"], "purchase")
        self.assertEqual(
            decision["appearance_cost"],
            Decimal("1.26"),
        )

    def test_on_pace_does_not_purchase(self):
        self.create_spend("200.00")

        decision = decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity("1.00"),
            moment=self.start + timedelta(days=2),
        )

        self.assertFalse(decision["purchase"])
        self.assertEqual(
            decision["reason"],
            "not_behind_pace",
        )

    def test_ahead_of_pace_does_not_purchase(self):
        self.create_spend("250.00")

        decision = decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity("1.00"),
            moment=self.start + timedelta(days=2),
        )

        self.assertFalse(decision["purchase"])
        self.assertEqual(
            decision["reason"],
            "not_behind_pace",
        )

    def test_unavailable_h3b1_opportunity_is_rejected(self):
        decision = decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity(
                "1.00",
                available=False,
                reason="inventory_collision",
            ),
            moment=self.start + timedelta(days=2),
        )

        self.assertFalse(decision["purchase"])
        self.assertEqual(
            decision["reason"],
            "inventory_collision",
        )

    def test_before_campaign_does_not_purchase(self):
        decision = decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity("1.00"),
            moment=self.start - timedelta(seconds=1),
        )

        self.assertFalse(decision["purchase"])
        self.assertEqual(
            decision["reason"],
            "campaign_not_started",
        )

    def test_after_campaign_does_not_purchase(self):
        decision = decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity("1.00"),
            moment=self.end,
        )

        self.assertFalse(decision["purchase"])
        self.assertEqual(
            decision["reason"],
            "campaign_ended",
        )

    def test_missing_campaign_window_is_invalid(self):
        campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Invalid Pacing Advertiser",
            campaign_name="Missing Window",
            total_budget=Decimal("100.00"),
        )

        with self.assertRaises(ValidationError):
            advertising_campaign_pacing_snapshot(
                campaign=campaign,
                moment=self.start,
            )

    def test_pacing_engine_is_read_only(self):
        reservations_before = (
            AdvertisingPlayoutReservation.objects.count()
        )
        spend_before = AdvertisingCampaignSpend.objects.count()

        decide_advertising_opportunity_purchase(
            campaign=self.campaign,
            opportunity=self.opportunity("1.00"),
            moment=self.start + timedelta(days=2),
        )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            reservations_before,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            spend_before,
        )
