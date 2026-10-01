from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from ballot.advertising_analytics import (
    advertising_campaign_delivery_analytics,
)
from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    AdvertisingRevenuePolicy,
    BillboardAd,
    record_advertising_appearance_play,
    record_advertising_campaign_spend,
    reserve_advertising_appearance,
)


class AdvertisingDeliveryCompletionContractTests(TestCase):

    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.placement = BillboardAd.PLACEMENT_CHOICES[0][0]

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="009-B6 Advertiser",
            campaign_name="009-B6 Completion Contract",
            total_budget=Decimal("500.00"),
            minimum_campaign_spend=Decimal("50.00"),
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
        )

        self.policy = AdvertisingRevenuePolicy.objects.create(
            name="009-B6 Completion Policy",
            platform_share_percent=Decimal("15.000"),
            is_active=True,
            effective_at=self.now - timedelta(days=1),
        )

    def analytics(self):
        return advertising_campaign_delivery_analytics(
            self.campaign
        )

    def make_creative(self, name="009-B6 Creative", seconds=12):
        return AdvertisingPlayoutCreative.objects.create(
            name=name,
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=seconds,
            is_active=True,
        )

    def purchase(self, creative, minutes=5, slot_price="2.0000"):
        reservations = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.now + timedelta(minutes=minutes),
            locked_slot_price=Decimal(slot_price),
            campaign=self.campaign,
        )

        record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        return reservations

    def test_zero_purchase_campaign_is_not_fully_delivered(self):
        analytics = self.analytics()

        self.assertEqual(analytics["purchased_appearances"], 0)
        self.assertEqual(analytics["played_appearances"], 0)
        self.assertEqual(analytics["outstanding_appearances"], 0)
        self.assertFalse(analytics["is_fully_delivered"])

    def test_partial_delivery_is_not_fully_delivered(self):
        creative = self.make_creative()

        first = self.purchase(
            creative,
            minutes=5,
        )
        self.purchase(
            creative,
            minutes=10,
        )

        record_advertising_appearance_play(
            appearance_id=first[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        analytics = self.analytics()

        self.assertEqual(analytics["purchased_appearances"], 2)
        self.assertEqual(analytics["played_appearances"], 1)
        self.assertEqual(analytics["outstanding_appearances"], 1)
        self.assertEqual(
            analytics["delivery_percentage"],
            Decimal("50.00"),
        )
        self.assertFalse(analytics["is_fully_delivered"])

    def test_fully_played_purchase_is_fully_delivered(self):
        creative = self.make_creative()

        reservations = self.purchase(
            creative,
            minutes=5,
        )

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        analytics = self.analytics()

        self.assertEqual(analytics["purchased_appearances"], 1)
        self.assertEqual(analytics["played_appearances"], 1)
        self.assertEqual(analytics["outstanding_appearances"], 0)
        self.assertEqual(
            analytics["delivery_percentage"],
            Decimal("100.00"),
        )
        self.assertTrue(analytics["is_fully_delivered"])

    def test_full_delivery_completes_eligible_campaign_lifecycle(self):
        creative = self.make_creative()

        reservations = self.purchase(
            creative,
            minutes=5,
        )

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        analytics = self.analytics()

        self.assertTrue(analytics["is_fully_delivered"])

        self.campaign.refresh_from_db()

        self.assertEqual(
            self.campaign.status,
            AdvertisingCampaign.STATUS_COMPLETED,
        )
