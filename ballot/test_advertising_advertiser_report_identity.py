import uuid

from django.test import TestCase

from ballot.models import AdvertisingCampaign


class AdvertisingAdvertiserReportIdentityTests(TestCase):

    def make_campaign(self, suffix):
        return AdvertisingCampaign.objects.create(
            advertiser_name=f"Advertiser {suffix}",
            campaign_name=f"Campaign {suffix}",
            contact_name=f"Contact {suffix}",
            email=f"advertiser{suffix}@example.com",
            phone="4045550100",
            total_budget="500.00",
            minimum_campaign_spend="50.00",
            status="active",
            internal_notes="",
        )

    def test_campaign_receives_report_token(self):
        campaign = self.make_campaign("one")

        self.assertIsNotNone(
            campaign.advertiser_report_token
        )

        self.assertIsInstance(
            campaign.advertiser_report_token,
            uuid.UUID,
        )

    def test_report_tokens_are_unique(self):
        first = self.make_campaign("one")
        second = self.make_campaign("two")

        self.assertNotEqual(
            first.advertiser_report_token,
            second.advertiser_report_token,
        )

    def test_report_token_is_not_editable(self):
        field = AdvertisingCampaign._meta.get_field(
            "advertiser_report_token"
        )

        self.assertFalse(field.editable)

    def test_report_token_is_unique_at_model_contract(self):
        field = AdvertisingCampaign._meta.get_field(
            "advertiser_report_token"
        )

        self.assertTrue(field.unique)

    def test_existing_style_campaign_creation_needs_no_token(self):
        campaign = self.make_campaign("legacy")

        campaign.refresh_from_db()

        self.assertTrue(
            campaign.advertiser_report_token
        )
