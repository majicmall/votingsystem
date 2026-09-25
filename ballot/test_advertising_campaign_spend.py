from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignSpend,
    AdvertisingPlayoutCreative,
    AdvertisingRevenuePolicy,
    BillboardAd,
    advertising_campaign_playout_remaining,
    advertising_campaign_playout_spend,
    record_advertising_campaign_spend,
    reserve_advertising_appearance,
)


class AdvertisingCampaignSpendTests(TestCase):

    def setUp(self):
        self.placement = BillboardAd.PLACEMENT_CHOICES[0][0]

        self.starts_at = timezone.make_aware(
            datetime(2026, 10, 1, 12, 0, 0)
        )

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Super Leo Test Advertiser",
            campaign_name="H3A Money Test",
            total_budget=Decimal("100.00"),
            minimum_campaign_spend=Decimal("50.00"),
        )

        self.policy = AdvertisingRevenuePolicy.objects.create(
            name="15 Percent Test Policy",
            platform_share_percent=Decimal("15.000"),
            is_active=True,
            effective_at=timezone.now() - timedelta(minutes=1),
        )

    def make_creative(self, seconds=6, creative_type="paid"):
        return AdvertisingPlayoutCreative.objects.create(
            name=f"{seconds} Second H3A Creative",
            creative_type=creative_type,
            duration_seconds=seconds,
        )

    def reserve(
        self,
        creative,
        price,
        starts_at=None,
        campaign=None,
    ):
        if starts_at is None:
            starts_at = self.starts_at

        if campaign is None and creative.creative_type == "paid":
            campaign = self.campaign

        return reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=starts_at,
            locked_slot_price=Decimal(price),
            campaign=campaign,
        )

    def test_six_second_spend_records_media_and_share(self):
        creative = self.make_creative(6)

        reservations = self.reserve(
            creative,
            "10.0000",
        )

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        self.assertEqual(spend.slot_count, 1)
        self.assertEqual(
            spend.locked_slot_price,
            Decimal("10.0000"),
        )
        self.assertEqual(
            spend.media_spend,
            Decimal("10.00"),
        )
        self.assertEqual(
            spend.platform_share_percent,
            Decimal("15.000"),
        )
        self.assertEqual(
            spend.platform_share_amount,
            Decimal("1.50"),
        )

    def test_one_hundred_media_spend_keeps_full_media_value(self):
        creative = self.make_creative(6)

        reservations = self.reserve(
            creative,
            "100.0000",
        )

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        self.assertEqual(
            spend.media_spend,
            Decimal("100.00"),
        )
        self.assertEqual(
            spend.platform_share_amount,
            Decimal("15.00"),
        )

        self.assertEqual(
            advertising_campaign_playout_spend(self.campaign),
            Decimal("100.00"),
        )

        # Critical accounting rule:
        # $100 media purchase consumes $100, not $115.
        self.assertEqual(
            advertising_campaign_playout_remaining(self.campaign),
            Decimal("0.00"),
        )

    def test_twelve_second_appearance_is_one_spend_record(self):
        creative = self.make_creative(12)

        reservations = self.reserve(
            creative,
            "0.7500",
        )

        self.assertEqual(len(reservations), 2)

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            1,
        )
        self.assertEqual(spend.slot_count, 2)
        self.assertEqual(
            spend.media_spend,
            Decimal("1.50"),
        )

        # 15% of $1.50 = $0.225 -> $0.23.
        self.assertEqual(
            spend.platform_share_amount,
            Decimal("0.23"),
        )

    def test_historical_share_is_locked(self):
        creative = self.make_creative(6)

        reservations = self.reserve(
            creative,
            "20.0000",
        )

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        self.policy.platform_share_percent = Decimal("25.000")
        self.policy.save()

        spend.refresh_from_db()

        self.assertEqual(
            spend.platform_share_percent,
            Decimal("15.000"),
        )
        self.assertEqual(
            spend.platform_share_amount,
            Decimal("3.00"),
        )

    def test_spend_cannot_exceed_remaining_media_budget(self):
        creative_a = self.make_creative(6)

        reservations_a = self.reserve(
            creative_a,
            "90.0000",
        )

        record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative_a,
            reservations=reservations_a,
            policy=self.policy,
        )

        self.assertEqual(
            advertising_campaign_playout_remaining(self.campaign),
            Decimal("10.00"),
        )

        creative_b = AdvertisingPlayoutCreative.objects.create(
            name="Second Paid Creative",
            creative_type="paid",
            duration_seconds=6,
        )

        reservations_b = self.reserve(
            creative_b,
            "11.0000",
            starts_at=self.starts_at + timedelta(seconds=12),
        )

        with self.assertRaises(ValidationError):
            record_advertising_campaign_spend(
                campaign=self.campaign,
                creative=creative_b,
                reservations=reservations_b,
                policy=self.policy,
            )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            1,
        )

    def test_paid_reservation_requires_campaign(self):
        creative = self.make_creative(6)

        with self.assertRaises(ValidationError):
            reserve_advertising_appearance(
                placement=self.placement,
                creative=creative,
                starts_at=self.starts_at,
                locked_slot_price=Decimal("1.0000"),
                campaign=None,
            )

    def test_house_reservation_does_not_require_campaign(self):
        creative = self.make_creative(
            6,
            creative_type="house",
        )

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.0000"),
            campaign=None,
        )

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].campaign_id)

    def test_advertise_here_does_not_require_campaign(self):
        creative = self.make_creative(
            6,
            creative_type="advertise_here",
        )

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.0000"),
            campaign=None,
        )

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].campaign_id)

    def test_reservations_must_belong_to_supplied_campaign(self):
        other_campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Other Advertiser",
            campaign_name="Other Campaign",
            total_budget=Decimal("100.00"),
        )

        creative = self.make_creative(6)

        reservations = self.reserve(
            creative,
            "5.0000",
        )

        with self.assertRaises(ValidationError):
            record_advertising_campaign_spend(
                campaign=other_campaign,
                creative=creative,
                reservations=reservations,
                policy=self.policy,
            )

    def test_spend_entry_is_immutable(self):
        creative = self.make_creative(6)

        reservations = self.reserve(
            creative,
            "10.0000",
        )

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
            policy=self.policy,
        )

        spend.media_spend = Decimal("1.00")

        with self.assertRaises(ValidationError):
            spend.save()

        spend.refresh_from_db()

        self.assertEqual(
            spend.media_spend,
            Decimal("10.00"),
        )

    def test_current_policy_is_used_when_policy_not_supplied(self):
        creative = self.make_creative(6)

        reservations = self.reserve(
            creative,
            "20.0000",
        )

        spend = record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=creative,
            reservations=reservations,
        )

        self.assertEqual(
            spend.platform_share_percent,
            Decimal("15.000"),
        )
        self.assertEqual(
            spend.platform_share_amount,
            Decimal("3.00"),
        )
