from datetime import datetime, time
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
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
    advertising_campaign_runner_queryset,
    run_autonomous_advertising_shopping_pass,
)


class AdvertisingAutonomousRunnerTests(TestCase):

    def aware(self, year, month, day, hour, minute=0, second=0):
        return timezone.make_aware(
            datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
            ),
            timezone.get_current_timezone(),
        )

    def setUp(self):
        # Monday, September 28, 2026.
        self.start = self.aware(2026, 9, 28, 18, 0)
        self.end = self.aware(2026, 9, 28, 22, 0)
        self.moment = self.aware(2026, 9, 28, 20, 0)

        self.daypart = AdvertisingDaypart.objects.create(
            name="H3B-3C Prime",
            slug="h3b-3c-prime",
            start_time=time(18, 0),
            end_time=time(22, 0),
            sort_order=10,
            is_active=True,
        )

        AdvertisingInventorySchedule.objects.create(
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            weekday=0,
            daypart=self.daypart,
            base_slot_price=Decimal("0.50"),
            traffic_multiplier=Decimal("1.0000"),
            is_active=True,
        )

    def make_campaign(
        self,
        *,
        name,
        status=AdvertisingCampaign.STATUS_ACTIVE,
        starts_at=None,
        ends_at=None,
        placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
        property_active=True,
        creative_active=True,
        assignment_active=True,
    ):
        starts_at = starts_at or self.start
        ends_at = ends_at or self.end

        campaign = AdvertisingCampaign.objects.create(
            advertiser_name=name,
            campaign_name=name,
            total_budget=Decimal("100.00"),
            minimum_campaign_spend=Decimal("0.00"),
            status=status,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        property_ad = BillboardAd.objects.create(
            campaign=campaign,
            advertiser_name=name,
            title=f"{name} Property",
            placement=placement,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
            allocated_budget=Decimal("100.00"),
            minimum_spend=Decimal("0.00"),
            rotation_weight=1,
            priority=100,
            is_active=property_active,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        creative = AdvertisingPlayoutCreative.objects.create(
            name=f"{name} Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            starts_at=starts_at,
            ends_at=ends_at,
            is_active=creative_active,
        )

        assignment = AdvertisingCampaignCreative.objects.create(
            campaign=campaign,
            creative=creative,
            is_active=assignment_active,
            priority=100,
            rotation_weight=100,
            approved_at=starts_at,
        )

        return campaign, property_ad, creative, assignment

    def test_runner_queryset_only_contains_current_active_campaigns(self):
        current, _, _, _ = self.make_campaign(
            name="Current Campaign",
        )

        self.make_campaign(
            name="Paused Campaign",
            status=AdvertisingCampaign.STATUS_PAUSED,
        )

        self.make_campaign(
            name="Future Campaign",
            starts_at=self.aware(2026, 9, 28, 21, 0),
            ends_at=self.aware(2026, 9, 28, 23, 0),
        )

        self.make_campaign(
            name="Ended Campaign",
            starts_at=self.aware(2026, 9, 28, 16, 0),
            ends_at=self.aware(2026, 9, 28, 19, 0),
        )

        ids = list(
            advertising_campaign_runner_queryset(
                moment=self.moment,
            ).values_list("pk", flat=True)
        )

        self.assertEqual(ids, [current.pk])

    def test_empty_runner_pass_returns_zero_summary(self):
        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
        )

        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["purchased_count"], 0)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(result["campaign_results"], [])

    def test_runner_can_purchase_for_active_campaign(self):
        campaign, _, _, _ = self.make_campaign(
            name="Buying Campaign",
        )

        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["purchased_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["failed_count"], 0)

        campaign_result = result["campaign_results"][0]

        self.assertEqual(
            campaign_result["campaign_id"],
            campaign.pk,
        )
        self.assertEqual(
            campaign_result["status"],
            "purchased",
        )
        self.assertTrue(campaign_result["purchased"])

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign,
            ).count(),
            1,
        )

    def test_runner_pass_buys_maximum_one_appearance_per_campaign(self):
        campaign, _, _, _ = self.make_campaign(
            name="One Purchase Campaign",
        )

        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertEqual(result["purchased_count"], 1)

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign,
            ).count(),
            1,
        )

        appearance_ids = set(
            AdvertisingPlayoutReservation.objects
            .filter(campaign=campaign)
            .values_list(
                "appearance_id",
                flat=True,
            )
        )

        self.assertEqual(len(appearance_ids), 1)

    def test_runner_processes_multiple_campaigns_independently(self):
        campaign_a, _, _, _ = self.make_campaign(
            name="Campaign A",
        )

        campaign_b, _, _, _ = self.make_campaign(
            name="Campaign B",
        )

        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(result["purchased_count"], 2)
        self.assertEqual(result["failed_count"], 0)

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign_a,
            ).count(),
            1,
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign_b,
            ).count(),
            1,
        )

    def test_skipped_campaign_does_not_stop_other_campaign(self):
        buying_campaign, _, _, _ = self.make_campaign(
            name="Buying Campaign",
        )

        skipped_campaign, skipped_property, _, _ = self.make_campaign(
            name="Skipped Campaign",
        )

        skipped_property.is_active = False
        skipped_property.save(
            update_fields=["is_active"]
        )

        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(result["purchased_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["failed_count"], 0)

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=buying_campaign,
            ).count(),
            1,
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=skipped_campaign,
            ).count(),
            0,
        )

    def test_campaign_exception_is_isolated(self):
        campaign_a, _, _, _ = self.make_campaign(
            name="Campaign A",
        )

        campaign_b, _, _, _ = self.make_campaign(
            name="Campaign B",
        )

        campaign_c, _, _, _ = self.make_campaign(
            name="Campaign C",
        )

        from ballot import models as ballot_models

        real_shopper = ballot_models.run_automated_advertising_shopper

        def isolated_shopper(*, campaign, **kwargs):
            if campaign.pk == campaign_b.pk:
                raise RuntimeError(
                    "Intentional campaign failure"
                )

            return real_shopper(
                campaign=campaign,
                **kwargs,
            )

        with patch(
            "ballot.models.run_automated_advertising_shopper",
            side_effect=isolated_shopper,
        ):
            result = run_autonomous_advertising_shopping_pass(
                moment=self.moment,
                lookahead_minutes=5,
            )

        self.assertEqual(result["processed_count"], 3)
        self.assertEqual(result["purchased_count"], 2)
        self.assertEqual(result["failed_count"], 1)

        failed = [
            item
            for item in result["campaign_results"]
            if item["status"] == "failed"
        ]

        self.assertEqual(len(failed), 1)
        self.assertEqual(
            failed[0]["campaign_id"],
            campaign_b.pk,
        )
        self.assertEqual(
            failed[0]["reason"],
            "campaign_runner_exception",
        )
        self.assertEqual(
            failed[0]["exception_type"],
            "RuntimeError",
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign_a,
            ).count(),
            1,
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign_b,
            ).count(),
            0,
        )

        self.assertEqual(
            AdvertisingCampaignSpend.objects.filter(
                campaign=campaign_c,
            ).count(),
            1,
        )

    def test_campaign_limit_caps_campaigns_attempted(self):
        self.make_campaign(name="Campaign A")
        self.make_campaign(name="Campaign B")
        self.make_campaign(name="Campaign C")

        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
            lookahead_minutes=5,
            campaign_limit=2,
        )

        self.assertEqual(result["processed_count"], 2)
        self.assertEqual(
            result["purchased_count"] +
            result["skipped_count"] +
            result["failed_count"],
            2,
        )

    def test_invalid_campaign_limit_is_rejected(self):
        for invalid in (0, -1, True, "2"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    run_autonomous_advertising_shopping_pass(
                        moment=self.moment,
                        campaign_limit=invalid,
                    )

    def test_invalid_lookahead_is_rejected(self):
        with self.assertRaises(ValidationError):
            run_autonomous_advertising_shopping_pass(
                moment=self.moment,
                lookahead_minutes=0,
            )

    def test_runner_summary_math_is_exact(self):
        self.make_campaign(
            name="Purchasing Campaign",
        )

        _, property_ad, _, _ = self.make_campaign(
            name="Skipping Campaign",
        )

        property_ad.is_active = False
        property_ad.save(
            update_fields=["is_active"]
        )

        result = run_autonomous_advertising_shopping_pass(
            moment=self.moment,
            lookahead_minutes=5,
        )

        self.assertEqual(
            result["processed_count"],
            (
                result["purchased_count"] +
                result["skipped_count"] +
                result["failed_count"]
            ),
        )
