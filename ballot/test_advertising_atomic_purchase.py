from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignSpend,
    AdvertisingDaypart,
    AdvertisingInventorySchedule,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    BillboardAd,
    execute_advertising_opportunity_purchase,
)


class AdvertisingAtomicPurchaseTests(TestCase):

    def aware(self, year, month, day, hour=0, minute=0, second=0):
        return timezone.make_aware(
            datetime(year, month, day, hour, minute, second),
            timezone.get_current_timezone(),
        )

    def setUp(self):
        self.campaign_start = self.aware(
            2026, 10, 1, 0, 0, 0
        )
        self.campaign_end = self.aware(
            2026, 10, 8, 0, 0, 0
        )

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Atomic Advertiser",
            campaign_name="Atomic Purchase Campaign",
            total_budget=Decimal("700.00"),
            minimum_campaign_spend=Decimal("0.00"),
            status=AdvertisingCampaign.STATUS_DRAFT,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
        )

        self.daypart = AdvertisingDaypart.objects.create(
            name="Atomic All Day",
            slug="atomic-all-day",
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            sort_order=1,
            is_active=True,
        )

        # 2026-10-03 is Saturday => weekday 5.
        self.schedule = AdvertisingInventorySchedule.objects.create(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            weekday=5,
            daypart=self.daypart,
            base_slot_price=Decimal("1.00"),
            traffic_multiplier=Decimal("1.250"),
            is_active=True,
        )

        self.creative_6 = AdvertisingPlayoutCreative.objects.create(
            name="Atomic 6 Second Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            is_active=True,
        )

        self.creative_12 = AdvertisingPlayoutCreative.objects.create(
            name="Atomic 12 Second Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=12,
            is_active=True,
        )

        self.starts_at = self.aware(
            2026, 10, 3, 12, 0, 0
        )

        # Two days into a seven-day $700 campaign means the linear
        # target is $200, so the campaign is comfortably behind pace.
        self.moment = self.campaign_start + timedelta(days=2)

    def test_six_second_purchase_creates_reservation_and_spend(self):
        result = execute_advertising_opportunity_purchase(
            campaign=self.campaign,
            creative=self.creative_6,
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            starts_at=self.starts_at,
            moment=self.moment,
        )

        self.assertTrue(result["purchased"])
        self.assertEqual(result["reason"], "purchased")

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            1,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            1,
        )

        reservation = (
            AdvertisingPlayoutReservation.objects.get()
        )
        spend = AdvertisingCampaignSpend.objects.get()

        self.assertEqual(
            reservation.locked_slot_price,
            Decimal("1.2500"),
        )
        self.assertEqual(
            spend.media_spend,
            Decimal("1.25"),
        )
        self.assertEqual(
            spend.appearance_id,
            reservation.appearance_id,
        )

    def test_twelve_second_purchase_is_two_consecutive_slots(self):
        result = execute_advertising_opportunity_purchase(
            campaign=self.campaign,
            creative=self.creative_12,
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            starts_at=self.starts_at,
            moment=self.moment,
        )

        self.assertTrue(result["purchased"])

        reservations = list(
            AdvertisingPlayoutReservation.objects.order_by(
                "sequence_number"
            )
        )

        self.assertEqual(len(reservations), 2)
        self.assertEqual(
            reservations[0].slot_start,
            self.starts_at,
        )
        self.assertEqual(
            reservations[1].slot_start,
            self.starts_at + timedelta(seconds=6),
        )

        self.assertEqual(
            reservations[0].appearance_id,
            reservations[1].appearance_id,
        )

        spend = AdvertisingCampaignSpend.objects.get()

        self.assertEqual(spend.slot_count, 2)
        self.assertEqual(
            spend.media_spend,
            Decimal("2.50"),
        )

    def test_existing_inventory_collision_makes_no_purchase(self):
        first = execute_advertising_opportunity_purchase(
            campaign=self.campaign,
            creative=self.creative_6,
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            starts_at=self.starts_at,
            moment=self.moment,
        )

        self.assertTrue(first["purchased"])

        reservations_before = (
            AdvertisingPlayoutReservation.objects.count()
        )
        spend_before = AdvertisingCampaignSpend.objects.count()

        second = execute_advertising_opportunity_purchase(
            campaign=self.campaign,
            creative=self.creative_6,
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            starts_at=self.starts_at,
            moment=self.moment,
        )

        self.assertFalse(second["purchased"])
        self.assertEqual(
            second["reason"],
            "inventory_collision",
        )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            reservations_before,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            spend_before,
        )

    def test_on_pace_creates_nothing(self):
        AdvertisingCampaignSpend.objects.create(
            campaign=self.campaign,
            creative=self.creative_6,
            appearance_id=__import__("uuid").uuid4(),
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            slot_count=1,
            locked_slot_price=Decimal("200.00"),
            media_spend=Decimal("200.00"),
            platform_share_percent=Decimal("15.000"),
            platform_share_amount=Decimal("30.00"),
        )

        reservations_before = (
            AdvertisingPlayoutReservation.objects.count()
        )
        spend_before = AdvertisingCampaignSpend.objects.count()

        result = execute_advertising_opportunity_purchase(
            campaign=self.campaign,
            creative=self.creative_6,
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            starts_at=self.starts_at,
            moment=self.moment,
        )

        self.assertFalse(result["purchased"])
        self.assertEqual(
            result["reason"],
            "not_behind_pace",
        )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            reservations_before,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            spend_before,
        )

    def test_h3a_failure_rolls_back_h2_reservations(self):
        with patch(
            "ballot.models.record_advertising_campaign_spend",
            side_effect=ValidationError(
                "Forced H3A failure."
            ),
        ):
            with self.assertRaises(ValidationError):
                execute_advertising_opportunity_purchase(
                    campaign=self.campaign,
                    creative=self.creative_12,
                    placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
                    starts_at=self.starts_at,
                    moment=self.moment,
                )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            0,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            0,
        )

    def test_spend_mismatch_rolls_back_everything(self):
        original_create = AdvertisingCampaignSpend.objects.create

        def bad_spend_create(**kwargs):
            kwargs["media_spend"] = Decimal("999.99")
            return original_create(**kwargs)

        with patch.object(
            AdvertisingCampaignSpend.objects,
            "create",
            side_effect=bad_spend_create,
        ):
            with self.assertRaises(ValidationError):
                execute_advertising_opportunity_purchase(
                    campaign=self.campaign,
                    creative=self.creative_6,
                    placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
                    starts_at=self.starts_at,
                    moment=self.moment,
                )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            0,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            0,
        )

    def test_unavailable_schedule_creates_nothing(self):
        result = execute_advertising_opportunity_purchase(
            campaign=self.campaign,
            creative=self.creative_6,
            placement=BillboardAd.PLACEMENT_VOTING_TOP,
            starts_at=self.starts_at,
            moment=self.moment,
        )

        self.assertFalse(result["purchased"])
        self.assertEqual(
            result["reason"],
            "no_inventory_schedule",
        )
        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            0,
        )
        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            0,
        )
