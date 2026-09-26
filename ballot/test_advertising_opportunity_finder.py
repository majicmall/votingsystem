from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingDaypart,
    AdvertisingInventorySchedule,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    BillboardAd,
    find_advertising_inventory_opportunity,
    reserve_advertising_appearance,
)


class AdvertisingOpportunityFinderTests(TestCase):

    def aware(self, year, month, day, hour, minute=0, second=0):
        return timezone.make_aware(
            datetime(year, month, day, hour, minute, second),
            timezone.get_current_timezone(),
        )

    def setUp(self):
        self.daypart = AdvertisingDaypart.objects.create(
            name="Prime Time",
            slug="prime-time-h3b-test",
            start_time=time(18, 0),
            end_time=time(23, 0),
            sort_order=10,
            is_active=True,
        )

        # 2026-09-28 is Monday.
        self.schedule = AdvertisingInventorySchedule.objects.create(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            weekday=0,
            daypart=self.daypart,
            base_slot_price=Decimal("0.50"),
            traffic_multiplier=Decimal("1.2500"),
            is_active=True,
        )

        self.creative_6 = AdvertisingPlayoutCreative.objects.create(
            name="H3B Six Second",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            is_active=True,
        )

        self.creative_12 = AdvertisingPlayoutCreative.objects.create(
            name="H3B Twelve Second",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=12,
            is_active=True,
        )

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="H3B Advertiser",
            campaign_name="H3B Opportunity Campaign",
            total_budget=Decimal("100.00"),
            minimum_campaign_spend=Decimal("0.00"),
            status=AdvertisingCampaign.STATUS_DRAFT,
            starts_at=self.aware(2026, 9, 28, 18, 0),
            ends_at=self.aware(2026, 9, 28, 23, 0),
        )

    def test_available_12_second_opportunity_returns_exact_cost(self):
        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_12,
            starts_at=self.aware(2026, 9, 28, 19, 0),
            campaign=self.campaign,
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["reason"], "available")
        self.assertEqual(result["slot_count"], 2)

        # 0.50 × 1.25 = 0.625 -> current_slot_price rounds to $0.63.
        self.assertEqual(result["slot_price"], Decimal("0.63"))
        self.assertEqual(result["appearance_cost"], Decimal("1.26"))

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            0,
        )

    def test_no_schedule_is_unavailable(self):
        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_6,
            starts_at=self.aware(2026, 9, 28, 17, 0),
            campaign=self.campaign,
        )

        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"],
            "before_campaign_window",
        )

    def test_outside_daypart_has_no_inventory_schedule(self):
        campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Wide Window Advertiser",
            campaign_name="Wide Window",
            total_budget=Decimal("100.00"),
            starts_at=self.aware(2026, 9, 28, 0, 0),
            ends_at=self.aware(2026, 9, 29, 0, 0),
        )

        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_6,
            starts_at=self.aware(2026, 9, 28, 17, 0),
            campaign=campaign,
        )

        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"],
            "no_inventory_schedule",
        )

    def test_existing_reservation_blocks_opportunity(self):
        starts_at = self.aware(2026, 9, 28, 19, 0)

        reserve_advertising_appearance(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_6,
            starts_at=starts_at,
            locked_slot_price=Decimal("0.63"),
            campaign=self.campaign,
        )

        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_12,
            starts_at=starts_at,
            campaign=self.campaign,
        )

        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"],
            "inventory_collision",
        )

    def test_cancelled_reservation_does_not_block_inventory(self):
        starts_at = self.aware(2026, 9, 28, 19, 0)

        reservations = reserve_advertising_appearance(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_6,
            starts_at=starts_at,
            locked_slot_price=Decimal("0.63"),
            campaign=self.campaign,
        )

        reservation = reservations[0]
        reservation.status = AdvertisingPlayoutReservation.STATUS_CANCELLED
        reservation.save(update_fields=["status"])

        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_6,
            starts_at=starts_at,
            campaign=self.campaign,
        )

        self.assertTrue(result["available"])

    def test_appearance_cannot_cross_daypart_boundary(self):
        # Keep the campaign open beyond the 23:00 daypart boundary so
        # this test isolates inventory/daypart behavior rather than
        # simultaneously crossing the campaign end boundary.
        campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Boundary Advertiser",
            campaign_name="Daypart Boundary Test",
            total_budget=Decimal("100.00"),
            starts_at=self.aware(2026, 9, 28, 18, 0),
            ends_at=self.aware(2026, 9, 29, 0, 0),
        )

        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_12,
            starts_at=self.aware(2026, 9, 28, 22, 59, 54),
            campaign=campaign,
        )

        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"],
            "crosses_inventory_boundary",
        )

    def test_appearance_cannot_exceed_campaign_window(self):
        campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Short Campaign",
            campaign_name="Short Window",
            total_budget=Decimal("100.00"),
            starts_at=self.aware(2026, 9, 28, 18, 0),
            ends_at=self.aware(2026, 9, 28, 19, 0),
        )

        result = find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_12,
            starts_at=self.aware(2026, 9, 28, 18, 59, 54),
            campaign=campaign,
        )

        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"],
            "after_campaign_window",
        )

    def test_finder_is_read_only(self):
        before = AdvertisingPlayoutReservation.objects.count()

        find_advertising_inventory_opportunity(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            creative=self.creative_12,
            starts_at=self.aware(2026, 9, 28, 20, 0),
            campaign=self.campaign,
        )

        after = AdvertisingPlayoutReservation.objects.count()

        self.assertEqual(before, after)
