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

    def test_fully_delivered_campaign_renders_completion_badge(self):
        campaign = AdvertisingCampaign.objects.create(
            campaign_name="Fully Delivered Campaign",
            advertiser_name="Completed Advertiser",
            total_budget="100.00",
        )

        self.client.force_login(self.staff)

        completed_analytics = {
            "purchased_appearances": 1,
            "played_appearances": 1,
            "delivery_percentage": "100.00",
            "media_spend": "100.00",
            "delivered_media_spend": "100.00",
            "outstanding_media_spend": "0.00",
            "outstanding_appearances": 0,
            "is_fully_delivered": True,
        }

        from unittest.mock import patch

        with patch(
            "ballot.advertising_analytics.advertising_campaign_delivery_analytics",
            return_value=completed_analytics,
        ):
            response = self.client.get(
                reverse("advertising_delivery_dashboard")
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "✓ FULLY DELIVERED",
        )

    def test_incomplete_campaign_does_not_render_completion_badge(self):
        campaign = AdvertisingCampaign.objects.create(
            campaign_name="Incomplete Campaign",
            advertiser_name="Incomplete Advertiser",
            total_budget="100.00",
        )

        self.client.force_login(self.staff)

        incomplete_analytics = {
            "purchased_appearances": 2,
            "played_appearances": 1,
            "delivery_percentage": "50.00",
            "media_spend": "100.00",
            "delivered_media_spend": "50.00",
            "outstanding_media_spend": "50.00",
            "outstanding_appearances": 1,
            "is_fully_delivered": False,
        }

        from unittest.mock import patch

        with patch(
            "ballot.advertising_analytics.advertising_campaign_delivery_analytics",
            return_value=incomplete_analytics,
        ):
            response = self.client.get(
                reverse("advertising_delivery_dashboard")
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "✓ FULLY DELIVERED",
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


class AdvertisingCompletedCampaignOperationsTests(TestCase):
    """
    009-B9 — Operations presentation contract for campaigns whose
    authoritative lifecycle has reached COMPLETED.

    These tests intentionally do not create a second completion authority.
    B8 owns lifecycle completion. B9 only verifies how Operations presents
    that authoritative state.
    """

    def setUp(self):
        User = get_user_model()

        self.staff = User.objects.create_user(
            username="b9staff",
            email="b9staff@example.com",
            password="test-pass-123",
            is_staff=True,
        )

    def make_completed_campaign(self):
        return AdvertisingCampaign.objects.create(
            campaign_name="B9 Completed Campaign",
            advertiser_name="B9 Completed Advertiser",
            total_budget="100.00",
            status=AdvertisingCampaign.STATUS_COMPLETED,
        )

    def completed_analytics(self):
        return {
            "purchased_appearances": 1,
            "played_appearances": 1,
            "delivery_percentage": "100.00",
            "media_spend": "100.00",
            "delivered_media_spend": "100.00",
            "outstanding_media_spend": "0.00",
            "outstanding_appearances": 0,
            "is_fully_delivered": True,
        }

    def test_completed_campaign_remains_visible_to_operations(self):
        self.make_completed_campaign()
        self.client.force_login(self.staff)

        from unittest.mock import patch

        with patch(
            "ballot.advertising_analytics."
            "advertising_campaign_delivery_analytics",
            return_value=self.completed_analytics(),
        ):
            response = self.client.get(
                reverse("advertising_delivery_dashboard")
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "B9 Completed Campaign",
        )
        self.assertContains(
            response,
            "B9 Completed Advertiser",
        )

    def test_completed_campaign_exposes_terminal_operations_state(self):
        self.make_completed_campaign()
        self.client.force_login(self.staff)

        from unittest.mock import patch

        with patch(
            "ballot.advertising_analytics."
            "advertising_campaign_delivery_analytics",
            return_value=self.completed_analytics(),
        ):
            response = self.client.get(
                reverse("advertising_delivery_dashboard")
            )

        self.assertEqual(response.status_code, 200)

        # B9 presentation contract.
        # Production template wiring comes in the next step.
        self.assertContains(
            response,
            "CAMPAIGN COMPLETE",
        )

    def test_completed_campaign_keeps_proof_of_play_available(self):
        campaign = self.make_completed_campaign()
        self.client.force_login(self.staff)

        from unittest.mock import patch

        with patch(
            "ballot.advertising_analytics."
            "advertising_campaign_delivery_analytics",
            return_value=self.completed_analytics(),
        ):
            response = self.client.get(
                reverse("advertising_delivery_dashboard")
            )

        self.assertEqual(response.status_code, 200)

        report_url = reverse(
            "advertising_campaign_delivery_report",
            args=[campaign.pk],
        )

        self.assertContains(
            response,
            report_url,
        )
        self.assertContains(
            response,
            "View Proof of Play",
        )
