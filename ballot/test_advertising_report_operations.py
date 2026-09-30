from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ballot.models import AdvertisingCampaign


class AdvertisingReportOperationsTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.staff = User.objects.create_superuser(
            username="b5operations",
            email="b5operations@example.com",
            password="B5-Test-Password-2026",
        )

        self.client.force_login(self.staff)

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="B5 Operations Advertiser",
            campaign_name="B5 Operations Campaign",
            contact_name="Operations",
            email="operations@example.com",
            phone="4045550100",
            total_budget="500.00",
            minimum_campaign_spend="50.00",
            status="active",
            internal_notes="",
        )

    def enable_url(self):
        return reverse(
            "admin:ballot_advertisingcampaign_report_enable",
            args=[self.campaign.pk],
        )

    def disable_url(self):
        return reverse(
            "admin:ballot_advertisingcampaign_report_disable",
            args=[self.campaign.pk],
        )

    def report_url(self):
        return reverse(
            "advertising_advertiser_delivery_report",
            kwargs={
                "token":
                    self.campaign.advertiser_report_token,
            },
        )

    def test_disable_requires_post(self):
        response = self.client.get(
            self.disable_url()
        )

        self.assertEqual(response.status_code, 405)

        self.campaign.refresh_from_db()

        self.assertTrue(
            self.campaign.advertiser_report_enabled
        )

    def test_enable_requires_post(self):
        self.campaign.advertiser_report_enabled = False
        self.campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        response = self.client.get(
            self.enable_url()
        )

        self.assertEqual(response.status_code, 405)

        self.campaign.refresh_from_db()

        self.assertFalse(
            self.campaign.advertiser_report_enabled
        )

    def test_operations_can_disable_report(self):
        original_token = (
            self.campaign.advertiser_report_token
        )

        response = self.client.post(
            self.disable_url()
        )

        self.assertEqual(response.status_code, 302)

        self.campaign.refresh_from_db()

        self.assertFalse(
            self.campaign.advertiser_report_enabled
        )

        self.assertEqual(
            self.campaign.advertiser_report_token,
            original_token,
        )

        public_response = self.client.get(
            self.report_url()
        )

        self.assertEqual(
            public_response.status_code,
            404,
        )

    def test_operations_can_reenable_report(self):
        original_token = (
            self.campaign.advertiser_report_token
        )

        self.campaign.advertiser_report_enabled = False
        self.campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        response = self.client.post(
            self.enable_url()
        )

        self.assertEqual(response.status_code, 302)

        self.campaign.refresh_from_db()

        self.assertTrue(
            self.campaign.advertiser_report_enabled
        )

        self.assertEqual(
            self.campaign.advertiser_report_token,
            original_token,
        )

        public_response = self.client.get(
            self.report_url()
        )

        self.assertEqual(
            public_response.status_code,
            200,
        )

    def test_campaign_admin_renders_report_controls(self):
        url = reverse(
            "admin:ballot_advertisingcampaign_change",
            args=[self.campaign.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "REPORT ACCESS ENABLED",
        )

        self.assertContains(
            response,
            "OPEN SECURE REPORT",
        )

        self.assertContains(
            response,
            "DISABLE REPORT ACCESS",
        )

    def test_disabled_campaign_admin_renders_enable_control(self):
        self.campaign.advertiser_report_enabled = False
        self.campaign.save(
            update_fields=[
                "advertiser_report_enabled",
                "updated_at",
            ]
        )

        url = reverse(
            "admin:ballot_advertisingcampaign_change",
            args=[self.campaign.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "REPORT ACCESS DISABLED",
        )

        self.assertContains(
            response,
            "ENABLE REPORT ACCESS",
        )
