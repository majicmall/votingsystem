import uuid

from django.test import TestCase
from django.urls import reverse

from ballot.models import AdvertisingCampaign


class AdvertisingAdvertiserDeliveryReportTests(TestCase):

    def make_campaign(self, suffix="one"):
        return AdvertisingCampaign.objects.create(
            advertiser_name=f"Advertiser {suffix}",
            campaign_name=f"Campaign {suffix}",
            contact_name=f"Contact {suffix}",
            email=f"{suffix}@example.com",
            phone="4045550100",
            total_budget="500.00",
            minimum_campaign_spend="50.00",
            status="active",
            internal_notes="",
        )

    def test_secure_report_route_uses_uuid_token(self):
        campaign = self.make_campaign()

        url = reverse(
            "advertising_advertiser_delivery_report",
            kwargs={
                "token": campaign.advertiser_report_token,
            },
        )

        self.assertEqual(
            url,
            (
                "/advertise/report/"
                f"{campaign.advertiser_report_token}/"
            ),
        )

    def test_valid_campaign_token_renders_report(self):
        campaign = self.make_campaign()

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "Verified Campaign Delivery Report",
        )

        self.assertContains(
            response,
            campaign.advertiser_name,
        )

        self.assertContains(
            response,
            campaign.campaign_name,
        )

    def test_report_does_not_require_staff_login(self):
        campaign = self.make_campaign()

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_unknown_uuid_returns_404(self):
        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": uuid.uuid4(),
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_campaign_id_is_not_report_authorization(self):
        campaign = self.make_campaign()

        response = self.client.get(
            f"/advertise/report/{campaign.pk}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_report_context_uses_authoritative_analytics(self):
        campaign = self.make_campaign()

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertEqual(response.status_code, 200)

        analytics = response.context["analytics"]

        self.assertEqual(
            analytics["purchased_appearances"],
            0,
        )
        self.assertEqual(
            analytics["played_appearances"],
            0,
        )
        self.assertEqual(
            analytics["outstanding_appearances"],
            0,
        )

    def test_report_marks_verified_proof_of_play_context(self):
        campaign = self.make_campaign()

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertTrue(
            response.context["verified_proof_of_play"]
        )

    def test_report_does_not_expose_token_in_visible_template(self):
        campaign = self.make_campaign()

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertNotContains(
            response,
            str(campaign.advertiser_report_token),
        )

    def test_active_campaign_report_does_not_show_terminal_completion_state(self):
        campaign = self.make_campaign()

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "CAMPAIGN COMPLETED",
        )

    def test_completed_campaign_report_shows_terminal_completion_state(self):
        campaign = self.make_campaign()

        campaign.status = AdvertisingCampaign.STATUS_COMPLETED
        campaign.save(update_fields=["status"])

        response = self.client.get(
            reverse(
                "advertising_advertiser_delivery_report",
                kwargs={
                    "token": campaign.advertiser_report_token,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "CAMPAIGN COMPLETED",
        )
