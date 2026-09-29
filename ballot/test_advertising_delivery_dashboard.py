from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ballot.models import AdvertisingCampaign


class AdvertisingDeliveryDashboardTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.staff = User.objects.create_user(
            username="b3staff",
            email="b3staff@example.com",
            password="test-pass-123",
            is_staff=True,
        )

        self.normal_user = User.objects.create_user(
            username="b3normal",
            email="b3normal@example.com",
            password="test-pass-123",
        )

    def test_dashboard_requires_authentication(self):
        response = self.client.get(
            reverse("advertising_delivery_dashboard")
        )

        self.assertEqual(response.status_code, 302)

    def test_dashboard_rejects_non_staff_user(self):
        self.client.force_login(self.normal_user)

        response = self.client.get(
            reverse("advertising_delivery_dashboard")
        )

        self.assertEqual(response.status_code, 302)

    def test_empty_dashboard_renders_for_staff(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("advertising_delivery_dashboard")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "No advertising campaigns yet.",
        )

    def test_campaign_dashboard_uses_authoritative_analytics(self):
        campaign = AdvertisingCampaign.objects.create(
            campaign_name="B3 Dashboard Campaign",
            advertiser_name="B3 Advertiser",
            total_budget="100.00",
        )

        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("advertising_delivery_dashboard")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "B3 Dashboard Campaign",
        )
        self.assertContains(
            response,
            "B3 Advertiser",
        )

    def test_campaign_report_requires_staff(self):
        campaign = AdvertisingCampaign.objects.create(
            campaign_name="Protected Campaign",
            advertiser_name="Protected Advertiser",
            total_budget="100.00",
        )

        self.client.force_login(self.normal_user)

        response = self.client.get(
            reverse(
                "advertising_campaign_delivery_report",
                args=[campaign.pk],
            )
        )

        self.assertEqual(response.status_code, 302)

    def test_campaign_report_renders_for_staff(self):
        campaign = AdvertisingCampaign.objects.create(
            campaign_name="Proof Campaign",
            advertiser_name="Proof Advertiser",
            total_budget="100.00",
        )

        self.client.force_login(self.staff)

        response = self.client.get(
            reverse(
                "advertising_campaign_delivery_report",
                args=[campaign.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Verified Proof of Play",
        )
        self.assertContains(
            response,
            "Proof Campaign",
        )

    def test_unknown_campaign_returns_404(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse(
                "advertising_campaign_delivery_report",
                args=[999999],
            )
        )

        self.assertEqual(response.status_code, 404)
