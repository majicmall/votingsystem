from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from ballot.advertising_analytics import (
    advertising_campaign_delivery_analytics,
)
from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignSpend,
    AdvertisingPlayoutCreative,
    AdvertisingRevenuePolicy,
    BillboardAd,
    record_advertising_appearance_play,
    record_advertising_campaign_spend,
    reserve_advertising_appearance,
)


class AdvertisingDeliveryAnalyticsTests(TestCase):

    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.placement = BillboardAd.PLACEMENT_CHOICES[0][0]

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="009 Analytics Advertiser",
            campaign_name="009-B2 Analytics Campaign",
            total_budget=Decimal("500.00"),
            minimum_campaign_spend=Decimal("50.00"),
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
        )

        self.policy = AdvertisingRevenuePolicy.objects.create(
            name="009 Analytics Policy",
            platform_share_percent=Decimal("15.000"),
            is_active=True,
            effective_at=self.now - timedelta(days=1),
        )

    def make_creative(self, name, seconds):
        return AdvertisingPlayoutCreative.objects.create(
            name=name,
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=seconds,
            is_active=True,
        )

    def purchase(
        self,
        creative,
        starts_at,
        slot_price,
    ):
        reservations = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=starts_at,
            locked_slot_price=Decimal(slot_price),
            campaign=self.campaign,
        )

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        return reservations, spend

    def test_empty_campaign_returns_zero_analytics(self):
        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        self.assertEqual(data["purchased_appearances"], 0)
        self.assertEqual(data["played_appearances"], 0)
        self.assertEqual(
            data["delivery_percentage"],
            Decimal("0.00"),
        )
        self.assertEqual(
            data["media_spend"],
            Decimal("0.00"),
        )
        self.assertEqual(
            data["delivered_media_spend"],
            Decimal("0.00"),
        )

    def test_twelve_second_purchase_is_one_appearance(self):
        creative = self.make_creative(
            "12 Second Analytics Creative",
            12,
        )

        reservations, spend = self.purchase(
            creative,
            self.now + timedelta(minutes=5),
            "1.2500",
        )

        self.assertEqual(len(reservations), 2)
        self.assertEqual(spend.slot_count, 2)

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        self.assertEqual(
            data["purchased_appearances"],
            1,
        )
        self.assertEqual(data["purchased_slots"], 2)
        self.assertEqual(
            data["reserved_appearances"],
            1,
        )
        self.assertEqual(data["reserved_slots"], 2)
        self.assertEqual(
            data["media_spend"],
            Decimal("2.50"),
        )

    def test_played_appearance_counts_once(self):
        creative = self.make_creative(
            "Played Analytics Creative",
            12,
        )

        reservations, _ = self.purchase(
            creative,
            self.now + timedelta(minutes=5),
            "2.0000",
        )

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        self.assertEqual(data["played_appearances"], 1)
        self.assertEqual(data["played_slots"], 2)
        self.assertEqual(
            data["delivery_percentage"],
            Decimal("100.00"),
        )
        self.assertEqual(
            data["delivered_media_spend"],
            Decimal("4.00"),
        )
        self.assertEqual(
            data["outstanding_media_spend"],
            Decimal("0.00"),
        )

    def test_partial_delivery_percentage_is_appearance_based(self):
        creative_a = self.make_creative(
            "Six Second Creative",
            6,
        )
        creative_b = self.make_creative(
            "Thirty Second Creative",
            30,
        )

        reservations_a, _ = self.purchase(
            creative_a,
            self.now + timedelta(minutes=5),
            "1.0000",
        )

        self.purchase(
            creative_b,
            self.now + timedelta(minutes=6),
            "1.0000",
        )

        record_advertising_appearance_play(
            appearance_id=reservations_a[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        # One of two appearances delivered = 50%.
        # The 30-second creative occupies five slots but still
        # represents only one advertising appearance.
        self.assertEqual(
            data["purchased_appearances"],
            2,
        )
        self.assertEqual(data["purchased_slots"], 6)
        self.assertEqual(data["played_appearances"], 1)
        self.assertEqual(
            data["delivery_percentage"],
            Decimal("50.00"),
        )

    def test_delivery_value_uses_locked_historical_spend(self):
        creative = self.make_creative(
            "Historical Spend Creative",
            6,
        )

        reservations, spend = self.purchase(
            creative,
            self.now + timedelta(minutes=5),
            "10.0000",
        )

        self.assertEqual(
            spend.media_spend,
            Decimal("10.00"),
        )

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        self.assertEqual(
            data["delivered_media_spend"],
            Decimal("10.00"),
        )

    def test_first_and_last_play_are_authoritative(self):
        creative = self.make_creative(
            "Proof Window Creative",
            6,
        )

        first_rows, _ = self.purchase(
            creative,
            self.now + timedelta(minutes=5),
            "1.0000",
        )

        second_rows, _ = self.purchase(
            creative,
            self.now + timedelta(minutes=10),
            "1.0000",
        )

        first_play = self.now + timedelta(minutes=5)
        last_play = self.now + timedelta(minutes=10)

        record_advertising_appearance_play(
            appearance_id=first_rows[0].appearance_id,
            played_at=first_play,
        )

        record_advertising_appearance_play(
            appearance_id=second_rows[0].appearance_id,
            played_at=last_play,
        )

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        self.assertEqual(
            data["first_played_at"],
            first_play,
        )
        self.assertEqual(
            data["last_played_at"],
            last_play,
        )

    def test_placement_breakdown_uses_appearance_counts(self):
        creative = self.make_creative(
            "Placement Analytics Creative",
            12,
        )

        reservations, _ = self.purchase(
            creative,
            self.now + timedelta(minutes=5),
            "1.0000",
        )

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        row = data["placement_breakdown"][0]

        self.assertEqual(row["placement"], self.placement)
        self.assertEqual(
            row["purchased_appearances"],
            1,
        )
        self.assertEqual(
            row["played_appearances"],
            1,
        )
        self.assertEqual(row["slot_count"], 2)
        self.assertEqual(
            row["media_spend"],
            Decimal("2.00"),
        )

    def test_creative_breakdown_uses_appearance_counts(self):
        creative = self.make_creative(
            "Creative Breakdown",
            12,
        )

        reservations, _ = self.purchase(
            creative,
            self.now + timedelta(minutes=5),
            "1.0000",
        )

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        data = advertising_campaign_delivery_analytics(
            self.campaign
        )

        row = data["creative_breakdown"][0]

        self.assertEqual(
            row["creative_id"],
            creative.pk,
        )
        self.assertEqual(
            row["creative_name"],
            str(creative),
        )
        self.assertEqual(
            row["purchased_appearances"],
            1,
        )
        self.assertEqual(
            row["played_appearances"],
            1,
        )
        self.assertEqual(row["slot_count"], 2)
