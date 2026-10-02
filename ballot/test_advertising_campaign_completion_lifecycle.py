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


class AdvertisingTerminalCampaignAdminProtectionTests(TestCase):
    """
    009-B10 — COMPLETED and CANCELLED are terminal campaign states.

    Ordinary Operations/admin workflow controls must never move either
    terminal state back into ACTIVE or PAUSED.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        self.staff = User.objects.create_superuser(
            username="b10admin",
            email="b10admin@example.com",
            password="test-pass-123",
        )

        self.client.force_login(self.staff)

    def make_campaign(self, status):
        return AdvertisingCampaign.objects.create(
            campaign_name=f"B10 {status} Campaign",
            advertiser_name="B10 Advertiser",
            total_budget="100.00",
            status=status,
        )

    def test_completed_campaign_cannot_be_bulk_activated(self):
        from ballot.admin import activate_advertising_campaigns
        from django.contrib import admin
        from django.test import RequestFactory

        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_COMPLETED
        )

        request = RequestFactory().post("/")
        request.user = self.staff

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware

        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)

        activate_advertising_campaigns(
            admin.site,
            request,
            AdvertisingCampaign.objects.filter(pk=campaign.pk),
        )

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_COMPLETED,
        )

    def test_completed_campaign_cannot_be_bulk_paused(self):
        from ballot.admin import pause_advertising_campaigns
        from django.contrib import admin
        from django.test import RequestFactory

        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_COMPLETED
        )

        request = RequestFactory().post("/")
        request.user = self.staff

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware

        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)

        pause_advertising_campaigns(
            admin.site,
            request,
            AdvertisingCampaign.objects.filter(pk=campaign.pk),
        )

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_COMPLETED,
        )

    def test_cancelled_campaign_cannot_be_bulk_activated(self):
        from ballot.admin import activate_advertising_campaigns
        from django.contrib import admin
        from django.test import RequestFactory

        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_CANCELLED
        )

        request = RequestFactory().post("/")
        request.user = self.staff

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware

        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)

        activate_advertising_campaigns(
            admin.site,
            request,
            AdvertisingCampaign.objects.filter(pk=campaign.pk),
        )

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_CANCELLED,
        )

    def test_cancelled_campaign_cannot_be_bulk_paused(self):
        from ballot.admin import pause_advertising_campaigns
        from django.contrib import admin
        from django.test import RequestFactory

        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_CANCELLED
        )

        request = RequestFactory().post("/")
        request.user = self.staff

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware

        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)

        pause_advertising_campaigns(
            admin.site,
            request,
            AdvertisingCampaign.objects.filter(pk=campaign.pk),
        )

        campaign.refresh_from_db()

        self.assertEqual(
            campaign.status,
            AdvertisingCampaign.STATUS_CANCELLED,
        )

    def test_completed_campaign_admin_control_is_terminal(self):
        from ballot.admin import AdvertisingCampaignAdmin
        from django.contrib import admin

        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_COMPLETED
        )

        campaign_admin = AdvertisingCampaignAdmin(
            AdvertisingCampaign,
            admin.site,
        )

        controls = str(
            campaign_admin.workflow_controls(campaign)
        )

        self.assertIn(
            "CAMPAIGN COMPLETE",
            controls,
        )

        self.assertNotIn(
            "ACTIVATE CAMPAIGN",
            controls,
        )

        self.assertNotIn(
            "PAUSE CAMPAIGN",
            controls,
        )

    def test_cancelled_campaign_admin_control_is_terminal(self):
        from ballot.admin import AdvertisingCampaignAdmin
        from django.contrib import admin

        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_CANCELLED
        )

        campaign_admin = AdvertisingCampaignAdmin(
            AdvertisingCampaign,
            admin.site,
        )

        controls = str(
            campaign_admin.workflow_controls(campaign)
        )

        self.assertIn(
            "CAMPAIGN CANCELLED",
            controls,
        )

        self.assertNotIn(
            "ACTIVATE CAMPAIGN",
            controls,
        )

        self.assertNotIn(
            "PAUSE CAMPAIGN",
            controls,
        )
