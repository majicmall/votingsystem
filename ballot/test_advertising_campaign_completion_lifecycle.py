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


class AdvertisingTerminalCampaignAdminFormProtectionTests(TestCase):
    """
    009-B11 — Terminal campaign status must be immutable through the
    ordinary Django Admin change form.

    COMPLETED and CANCELLED campaigns retain operational visibility,
    but their lifecycle status may not be manually reopened.
    """

    def setUp(self):
        from django.contrib import admin

        from ballot.admin import AdvertisingCampaignAdmin

        self.campaign_admin = AdvertisingCampaignAdmin(
            AdvertisingCampaign,
            admin.site,
        )

    def make_campaign(self, status):
        return AdvertisingCampaign.objects.create(
            campaign_name=f"B11 {status} Campaign",
            advertiser_name="B11 Advertiser",
            total_budget="100.00",
            status=status,
        )

    def test_completed_campaign_status_is_readonly_in_admin(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_COMPLETED
        )

        readonly = self.campaign_admin.get_readonly_fields(
            request=None,
            obj=campaign,
        )

        self.assertIn("status", readonly)

    def test_cancelled_campaign_status_is_readonly_in_admin(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_CANCELLED
        )

        readonly = self.campaign_admin.get_readonly_fields(
            request=None,
            obj=campaign,
        )

        self.assertIn("status", readonly)

    def test_active_campaign_status_is_not_terminally_locked(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_ACTIVE
        )

        readonly = self.campaign_admin.get_readonly_fields(
            request=None,
            obj=campaign,
        )

        self.assertNotIn("status", readonly)

    def test_pending_campaign_status_is_not_terminally_locked(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_PENDING
        )

        readonly = self.campaign_admin.get_readonly_fields(
            request=None,
            obj=campaign,
        )

        self.assertNotIn("status", readonly)


class AdvertisingTerminalCampaignCustomUrlProtectionTests(TestCase):
    """
    009-B12 — Terminal campaigns must not expose ordinary activate/pause
    confirmation screens through manually entered Django Admin URLs.

    The underlying B10 mutation guards remain authoritative; this contract
    closes the remaining custom-URL workflow doorway.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        self.staff = User.objects.create_superuser(
            username="b12admin",
            email="b12admin@example.com",
            password="test-pass-123",
        )

        self.client.force_login(self.staff)

    def make_campaign(self, status):
        return AdvertisingCampaign.objects.create(
            campaign_name=f"B12 {status} Campaign",
            advertiser_name="B12 Advertiser",
            total_budget="100.00",
            status=status,
        )

    def admin_url(self, campaign, action):
        from django.urls import reverse

        return reverse(
            f"admin:ballot_advertisingcampaign_{action}",
            args=[campaign.pk],
        )

    def change_url(self, campaign):
        from django.urls import reverse

        return reverse(
            "admin:ballot_advertisingcampaign_change",
            args=[campaign.pk],
        )

    def assert_terminal_get_redirects(self, campaign, action):
        response = self.client.get(
            self.admin_url(campaign, action),
        )

        self.assertRedirects(
            response,
            self.change_url(campaign),
        )

    def test_completed_campaign_activate_url_redirects_to_change_page(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_COMPLETED
        )

        self.assert_terminal_get_redirects(
            campaign,
            "activate",
        )

    def test_completed_campaign_pause_url_redirects_to_change_page(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_COMPLETED
        )

        self.assert_terminal_get_redirects(
            campaign,
            "pause",
        )

    def test_cancelled_campaign_activate_url_redirects_to_change_page(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_CANCELLED
        )

        self.assert_terminal_get_redirects(
            campaign,
            "activate",
        )

    def test_cancelled_campaign_pause_url_redirects_to_change_page(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_CANCELLED
        )

        self.assert_terminal_get_redirects(
            campaign,
            "pause",
        )

    def test_pending_campaign_activate_url_still_renders_confirmation(self):
        campaign = self.make_campaign(
            AdvertisingCampaign.STATUS_PENDING
        )

        response = self.client.get(
            self.admin_url(campaign, "activate"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "ACTIVATE CAMPAIGN",
        )
