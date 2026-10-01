from unittest.mock import patch

from django.test import TestCase

from ballot.advertising_lifecycle import (
    complete_campaign_if_fully_delivered,
)
from ballot.models import AdvertisingCampaign


class AdvertisingCampaignCompletionLifecycleTests(TestCase):

    def make_campaign(self, status=AdvertisingCampaign.STATUS_ACTIVE):
        return AdvertisingCampaign.objects.create(
            campaign_name="B8 Lifecycle Campaign",
            advertiser_name="B8 Advertiser",
            total_budget="100.00",
            status=status,
        )

    def analytics(self, fully_delivered):
        return {
            "is_fully_delivered": fully_delivered,
        }

    def test_active_fully_delivered_campaign_becomes_completed(self):
        campaign = self.make_campaign()

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(True),
        ):
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertTrue(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_COMPLETED,
        )

    def test_incomplete_campaign_remains_active(self):
        campaign = self.make_campaign()

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(False),
        ):
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertFalse(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_ACTIVE,
        )

    def test_paused_fully_delivered_campaign_can_complete(self):
        campaign = self.make_campaign(
            status=AdvertisingCampaign.STATUS_PAUSED,
        )

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(True),
        ):
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertTrue(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_COMPLETED,
        )

    def test_draft_campaign_cannot_jump_to_completed(self):
        campaign = self.make_campaign(
            status=AdvertisingCampaign.STATUS_DRAFT,
        )

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(True),
        ) as analytics_mock:
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertFalse(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_DRAFT,
        )

        analytics_mock.assert_not_called()

    def test_pending_campaign_cannot_jump_to_completed(self):
        campaign = self.make_campaign(
            status=AdvertisingCampaign.STATUS_PENDING,
        )

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(True),
        ) as analytics_mock:
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertFalse(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_PENDING,
        )

        analytics_mock.assert_not_called()

    def test_cancelled_campaign_is_never_rewritten(self):
        campaign = self.make_campaign(
            status=AdvertisingCampaign.STATUS_CANCELLED,
        )

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(True),
        ) as analytics_mock:
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertFalse(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_CANCELLED,
        )

        analytics_mock.assert_not_called()

    def test_completed_campaign_is_idempotent(self):
        campaign = self.make_campaign(
            status=AdvertisingCampaign.STATUS_COMPLETED,
        )

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(True),
        ) as analytics_mock:
            changed = complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertFalse(changed)
        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_COMPLETED,
        )

        analytics_mock.assert_not_called()

    def test_completion_service_does_not_change_analytics_contract(self):
        campaign = self.make_campaign()

        with patch(
            "ballot.advertising_lifecycle."
            "advertising_campaign_delivery_analytics",
            return_value=self.analytics(False),
        ):
            complete_campaign_if_fully_delivered(campaign)

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_ACTIVE,
        )
