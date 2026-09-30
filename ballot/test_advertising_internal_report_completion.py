from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    AdvertisingRevenuePolicy,
    BillboardAd,
    record_advertising_appearance_play,
    record_advertising_campaign_spend,
    reserve_advertising_appearance,
)


class AdvertisingInternalReportCompletionTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.staff = User.objects.create_user(
            username="b7-report-staff",
            email="b7-report-staff@example.com",
            password="test-pass-123",
            is_staff=True,
        )

        self.now = timezone.now().replace(microsecond=0)
        self.placement = BillboardAd.PLACEMENT_CHOICES[0][0]

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="009-B7 Report Advertiser",
            campaign_name="009-B7 Internal Report Completion",
            total_budget=Decimal("500.00"),
            minimum_campaign_spend=Decimal("50.00"),
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
        )

        self.policy = AdvertisingRevenuePolicy.objects.create(
            name="009-B7 Report Policy",
            platform_share_percent=Decimal("15.000"),
            is_active=True,
            effective_at=self.now - timedelta(days=1),
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="009-B7 Report Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=12,
            is_active=True,
        )

        self.client.force_login(self.staff)

    def purchase(self, minutes):
        reservations = reserve_advertising_appearance(
            placement=self.placement,
            creative=self.creative,
            starts_at=self.now + timedelta(minutes=minutes),
            locked_slot_price=Decimal("2.0000"),
            campaign=self.campaign,
        )

        record_advertising_campaign_spend(
            campaign=self.campaign,
            creative=self.creative,
            reservations=reservations,
            policy=self.policy,
        )

        return reservations

    def report(self):
        return self.client.get(
            reverse(
                "advertising_campaign_delivery_report",
                args=[self.campaign.pk],
            )
        )

    def test_fully_delivered_campaign_report_shows_completion_badge(self):
        reservations = self.purchase(minutes=5)

        record_advertising_appearance_play(
            appearance_id=reservations[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        response = self.report()

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "✓ FULLY DELIVERED",
        )

    def test_partial_campaign_report_hides_completion_badge(self):
        first = self.purchase(minutes=5)
        self.purchase(minutes=10)

        record_advertising_appearance_play(
            appearance_id=first[0].appearance_id,
            played_at=self.now + timedelta(minutes=5),
        )

        response = self.report()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "✓ FULLY DELIVERED",
        )

    def test_zero_purchase_campaign_report_hides_completion_badge(self):
        response = self.report()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "✓ FULLY DELIVERED",
        )
