from django.core.exceptions import ValidationError
from django.test import TestCase

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    BillboardAd,
)


class AdvertisingPresentationBridgeTests(TestCase):

    def setUp(self):
        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="009 Test Advertiser",
            campaign_name="009 Presentation Campaign",
            email="009@example.com",
            total_budget="500.00",
            minimum_campaign_spend="50.00",
        )

        self.billboard = BillboardAd.objects.create(
            campaign=self.campaign,
            advertiser_name="009 Test Advertiser",
            title="009 Live Billboard",
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            destination_url="https://example.com/",
            call_to_action="Learn More",
            allocated_budget="500.00",
            minimum_spend="50.00",
            is_active=True,
        )

    def test_paid_playout_creative_can_reference_campaign_billboard(self):
        creative = AdvertisingPlayoutCreative(
            name="009 Paid Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            billboard_ad=self.billboard,
            duration_seconds=6,
            is_active=True,
        )

        creative.full_clean()
        creative.save()

        self.assertEqual(
            creative.billboard_ad_id,
            self.billboard.id,
        )

        self.assertEqual(
            creative.billboard_ad.campaign_id,
            self.campaign.id,
        )

    def test_billboard_presentation_exposes_live_delivery_fields(self):
        creative = AdvertisingPlayoutCreative.objects.create(
            name="009 Delivery Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            billboard_ad=self.billboard,
            duration_seconds=6,
            is_active=True,
        )

        self.assertEqual(
            creative.billboard_ad.title,
            "009 Live Billboard",
        )

        self.assertEqual(
            creative.billboard_ad.destination_url,
            "https://example.com/",
        )

        self.assertEqual(
            creative.billboard_ad.call_to_action,
            "Learn More",
        )

    def test_paid_creative_rejects_campaignless_billboard(self):
        orphan = BillboardAd.objects.create(
            advertiser_name="Orphan Advertiser",
            title="Orphan Billboard",
            placement=BillboardAd.PLACEMENT_HOMEPAGE_TOP,
            is_active=True,
        )

        creative = AdvertisingPlayoutCreative(
            name="Invalid Paid Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            billboard_ad=orphan,
            duration_seconds=6,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            creative.full_clean()

    def test_house_creative_may_exist_without_billboard_bridge(self):
        creative = AdvertisingPlayoutCreative(
            name="ATL House Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_HOUSE,
            duration_seconds=6,
            is_active=True,
        )

        creative.full_clean()
