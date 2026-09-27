from datetime import datetime, time
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignCreative,
    AdvertisingCampaignSpend,
    AdvertisingDaypart,
    AdvertisingInventorySchedule,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    BillboardAd,
    advertising_campaign_current_properties,
    choose_automated_advertising_purchase_candidate,
    find_automated_advertising_purchase_candidates,
    run_automated_advertising_shopper,
)


class AdvertisingAutoShopperTests(TestCase):

    def aware(self, year, month, day, hour, minute=0, second=0):
        return timezone.make_aware(
            datetime(year, month, day, hour, minute, second),
            timezone.get_current_timezone(),
        )

    def setUp(self):
        # Monday, September 28, 2026.
        self.campaign_start = self.aware(2026, 9, 28, 18, 0)
        self.campaign_end = self.aware(2026, 9, 28, 22, 0)
        self.moment = self.aware(2026, 9, 28, 20, 0)

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="H3B-3B Advertiser",
            campaign_name="Autonomous Shopper Campaign",
            total_budget=Decimal("100.00"),
            minimum_campaign_spend=Decimal("0.00"),
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
        )

        self.property = BillboardAd.objects.create(
            campaign=self.campaign,
            advertiser_name="H3B-3B Advertiser",
            title="Homepage Campaign Property",
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
            allocated_budget=Decimal("100.00"),
            minimum_spend=Decimal("0.00"),
            rotation_weight=1,
            priority=100,
            is_active=True,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
        )

        self.daypart = AdvertisingDaypart.objects.create(
            name="H3B-3B Prime",
            slug="h3b-3b-prime",
            start_time=time(18, 0),
            end_time=time(22, 0),
            sort_order=10,
            is_active=True,
        )

        self.schedule = AdvertisingInventorySchedule.objects.create(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            weekday=0,
            daypart=self.daypart,
            base_slot_price=Decimal("0.50"),
            traffic_multiplier=Decimal("1.0000"),
            is_active=True,
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="H3B-3B Paid Six",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
            is_active=True,
        )

        self.assignment = AdvertisingCampaignCreative.objects.create(
            campaign=self.campaign,
            creative=self.creative,
            is_active=True,
            priority=100,
            rotation_weight=100,
            approved_at=self.campaign_start,
        )

    def test_current_properties_are_campaign_owned_and_current(self):
        properties = advertising_campaign_current_properties(
            campaign=self.campaign,
            moment=self.moment,
        )

        self.assertEqual(
            [property_ad.pk for property_ad in properties],
            [self.property.pk],
        )

    def test_paused_campaign_does_not_shop(self):
        self.campaign.status = AdvertisingCampaign.STATUS_PAUSED
        self.campaign.save(update_fields=["status"])

        result = run_automated_advertising_shopper(
            campaign=self.campaign,
            moment=self.moment,
        )

        self.assertFalse(result["purchased"])
        self.assertEqual(result["reason"], "campaign_not_active")
        self.assertEqual(AdvertisingPlayoutReservation.objects.count(), 0)
        self.assertEqual(AdvertisingCampaignSpend.objects.count(), 0)

    def test_campaign_without_authorized_creative_does_not_shop(self):
        self.assignment.is_active = False
        self.assignment.save(update_fields=["is_active"])

        result = run_automated_advertising_shopper(
            campaign=self.campaign,
            moment=self.moment,
        )

        self.assertFalse(result["purchased"])
        self.assertEqual(
            result["reason"],
            "no_authorized_campaign_creatives",
        )
        self.assertEqual(AdvertisingPlayoutReservation.objects.count(), 0)
        self.assertEqual(AdvertisingCampaignSpend.objects.count(), 0)

    def test_campaign_without_current_property_does_not_shop(self):
        self.property.is_active = False
        self.property.save(update_fields=["is_active"])

        result = run_automated_advertising_shopper(
            campaign=self.campaign,
            moment=self.moment,
        )

        self.assertFalse(result["purchased"])
        self.assertEqual(
            result["reason"],
            "no_current_campaign_properties",
        )
        self.assertEqual(AdvertisingPlayoutReservation.objects.count(), 0)

    def test_candidate_discovery_is_read_only(self):
        candidates = find_automated_advertising_purchase_candidates(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertTrue(candidates)
        self.assertEqual(
            candidates[0]["placement"],
            BillboardAd.PLACEMENT_HOMEPAGE_TOP,
        )
        self.assertEqual(candidates[0]["creative"], self.creative)

        self.assertEqual(AdvertisingPlayoutReservation.objects.count(), 0)
        self.assertEqual(AdvertisingCampaignSpend.objects.count(), 0)

    def test_shopper_purchases_exactly_one_appearance(self):
        result = run_automated_advertising_shopper(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertTrue(result["purchased"])
        self.assertEqual(result["reason"], "purchased")

        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            1,
        )

        spend = AdvertisingCampaignSpend.objects.get()

        self.assertEqual(spend.campaign, self.campaign)
        self.assertEqual(spend.creative, self.creative)
        self.assertEqual(
            spend.placement,
            BillboardAd.PLACEMENT_HOMEPAGE_TOP,
        )

        # Six-second creative = exactly one reservation.
        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            1,
        )

        reservation = AdvertisingPlayoutReservation.objects.get()

        self.assertEqual(reservation.campaign, self.campaign)
        self.assertEqual(reservation.creative, self.creative)
        self.assertEqual(
            reservation.appearance_id,
            spend.appearance_id,
        )

    def test_one_controller_invocation_never_buys_two_appearances(self):
        second_creative = AdvertisingPlayoutCreative.objects.create(
            name="H3B-3B Second Paid Six",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
            is_active=True,
        )

        AdvertisingCampaignCreative.objects.create(
            campaign=self.campaign,
            creative=second_creative,
            is_active=True,
            priority=200,
            rotation_weight=100,
            approved_at=self.campaign_start,
        )

        result = run_automated_advertising_shopper(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertTrue(result["purchased"])
        self.assertGreaterEqual(
            result["candidates_considered"],
            1,
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.count(),
            1,
        )

        appearance_ids = set(
            AdvertisingPlayoutReservation.objects.values_list(
                "appearance_id",
                flat=True,
            )
        )

        self.assertEqual(len(appearance_ids), 1)

    def test_unauthorized_paid_creative_is_never_selected(self):
        rogue = AdvertisingPlayoutCreative.objects.create(
            name="Unauthorized Paid Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
            is_active=True,
        )

        candidates = find_automated_advertising_purchase_candidates(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        candidate_creatives = {
            candidate["creative"].pk
            for candidate in candidates
        }

        self.assertIn(self.creative.pk, candidate_creatives)
        self.assertNotIn(rogue.pk, candidate_creatives)

    def test_property_priority_breaks_same_time_tie(self):
        second_property = BillboardAd.objects.create(
            campaign=self.campaign,
            advertiser_name="H3B-3B Advertiser",
            title="Voting Campaign Property",
            placement=BillboardAd.PLACEMENT_VOTING_TOP,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
            allocated_budget=Decimal("0.00"),
            minimum_spend=Decimal("0.00"),
            rotation_weight=1,
            priority=10,
            is_active=True,
            starts_at=self.campaign_start,
            ends_at=self.campaign_end,
        )

        AdvertisingInventorySchedule.objects.create(
            placement=BillboardAd.PLACEMENT_VOTING_TOP,
            weekday=0,
            daypart=self.daypart,
            base_slot_price=Decimal("0.50"),
            traffic_multiplier=Decimal("1.0000"),
            is_active=True,
        )

        candidates = find_automated_advertising_purchase_candidates(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        winner = choose_automated_advertising_purchase_candidate(
            candidates=candidates,
        )

        self.assertIsNotNone(winner)
        self.assertEqual(
            winner["property"].pk,
            second_property.pk,
        )

    def test_inactive_property_is_not_candidate(self):
        self.property.is_active = False
        self.property.save(update_fields=["is_active"])

        candidates = find_automated_advertising_purchase_candidates(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertEqual(candidates, [])

    def test_candidate_search_skips_collision_and_finds_later_slot(self):
        first = run_automated_advertising_shopper(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertTrue(first["purchased"])

        # The next discovery must not reuse the already purchased six-second
        # unit. It should search forward and find later inventory.
        candidates = find_automated_advertising_purchase_candidates(
            campaign=self.campaign,
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertTrue(candidates)

        self.assertGreater(
            candidates[0]["starts_at"],
            first["candidate"]["starts_at"],
        )
