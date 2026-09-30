from django.test import TestCase
from django.urls import reverse

from ballot.models import AdvertisingCampaign


class AdvertisingReportAccessControlTests(TestCase):

    def make_campaign(self, suffix="one", **overrides):
        values = {
            "advertiser_name": f"Advertiser {suffix}",
            "campaign_name": f"Campaign {suffix}",
            "contact_name": f"Contact {suffix}",
            "email": f"{suffix}@example.com",
            "phone": "4045550100",
            "total_budget": "500.00",
            "minimum_campaign_spend": "50.00",
            "status": "active",
            "internal_notes": "",
        }

        values.update(overrides)

        return AdvertisingCampaign.objects.create(**values)

    def report_url(self, campaign):
        return reverse(
            "advertising_advertiser_delivery_report",
            kwargs={
                "token": campaign.advertiser_report_token,
            },
        )

    def test_report_access_defaults_enabled(self):
        campaign = self.make_campaign()

        self.assertTrue(
            campaign.advertiser_report_enabled
        )

    def test_enabled_report_remains_accessible(self):
        campaign = self.make_campaign()

        response = self.client.get(
            self.report_url(campaign)
        )

        self.assertEqual(response.status_code, 200)

    def test_disabled_report_returns_404(self):
        campaign = self.make_campaign(
            advertiser_report_enabled=False,
        )

        response = self.client.get(
            self.report_url(campaign)
        )

        self.assertEqual(response.status_code, 404)

    def test_disabling_report_does_not_change_token(self):
        campaign = self.make_campaign()

        original_token = campaign.advertiser_report_token

        campaign.advertiser_report_enabled = False
        campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.advertiser_report_token,
            original_token,
        )

    def test_report_can_be_reenabled(self):
        campaign = self.make_campaign(
            advertiser_report_enabled=False,
        )

        disabled_response = self.client.get(
            self.report_url(campaign)
        )

        self.assertEqual(
            disabled_response.status_code,
            404,
        )

        campaign.advertiser_report_enabled = True
        campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        enabled_response = self.client.get(
            self.report_url(campaign)
        )

        self.assertEqual(
            enabled_response.status_code,
            200,
        )

    def test_access_control_does_not_require_new_token(self):
        campaign = self.make_campaign()

        token = campaign.advertiser_report_token

        campaign.advertiser_report_enabled = False
        campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        campaign.advertiser_report_enabled = True
        campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.advertiser_report_token,
            token,
        )

        response = self.client.get(
            self.report_url(campaign)
        )

        self.assertEqual(response.status_code, 200)
