from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignCreative,
    AdvertisingPlayoutCreative,
    advertising_campaign_creative_is_authorized,
    advertising_campaign_eligible_creative_assignments,
)


class AdvertisingCampaignCreativeTests(TestCase):

    def setUp(self):
        self.now = timezone.now()

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="H3B-3A Advertiser",
            campaign_name="H3B-3A Campaign",
            contact_name="Campaign Owner",
            email="campaign@example.com",
            phone="4045550100",
            total_budget="500.00",
            minimum_campaign_spend="0.00",
            status="active",
            starts_at=self.now - timedelta(days=1),
            ends_at=self.now + timedelta(days=7),
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="Authorized Six Second Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            priority=100,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
            is_active=True,
        )

    def make_assignment(self, **overrides):
        values = {
            "campaign": self.campaign,
            "creative": self.creative,
            "is_active": True,
            "rotation_weight": 100,
            "priority": 100,
            "approved_at": self.now,
        }
        values.update(overrides)

        return AdvertisingCampaignCreative.objects.create(**values)

    def test_active_assignment_authorizes_paid_creative(self):
        self.make_assignment()

        self.assertTrue(
            advertising_campaign_creative_is_authorized(
                campaign=self.campaign,
                creative=self.creative,
                moment=self.now,
            )
        )

    def test_unassigned_creative_is_not_authorized(self):
        self.assertFalse(
            advertising_campaign_creative_is_authorized(
                campaign=self.campaign,
                creative=self.creative,
                moment=self.now,
            )
        )

    def test_inactive_assignment_is_not_authorized(self):
        self.make_assignment(is_active=False)

        self.assertFalse(
            advertising_campaign_creative_is_authorized(
                campaign=self.campaign,
                creative=self.creative,
                moment=self.now,
            )
        )

    def test_inactive_creative_is_not_authorized(self):
        self.make_assignment()

        self.creative.is_active = False
        self.creative.save(update_fields=["is_active"])

        self.assertFalse(
            advertising_campaign_creative_is_authorized(
                campaign=self.campaign,
                creative=self.creative,
                moment=self.now,
            )
        )

    def test_future_creative_is_not_authorized(self):
        self.creative.starts_at = self.now + timedelta(hours=1)
        self.creative.save(update_fields=["starts_at"])

        self.make_assignment()

        self.assertFalse(
            advertising_campaign_creative_is_authorized(
                campaign=self.campaign,
                creative=self.creative,
                moment=self.now,
            )
        )

    def test_expired_creative_is_not_authorized(self):
        self.creative.ends_at = self.now
        self.creative.save(update_fields=["ends_at"])

        self.make_assignment()

        self.assertFalse(
            advertising_campaign_creative_is_authorized(
                campaign=self.campaign,
                creative=self.creative,
                moment=self.now,
            )
        )

    def test_non_paid_creative_cannot_be_assigned(self):
        self.creative.creative_type = (
            AdvertisingPlayoutCreative.TYPE_HOUSE
        )
        self.creative.save(update_fields=["creative_type"])

        assignment = AdvertisingCampaignCreative(
            campaign=self.campaign,
            creative=self.creative,
        )

        with self.assertRaises(ValidationError):
            assignment.full_clean()

    def test_duplicate_campaign_creative_assignment_rejected(self):
        self.make_assignment()

        duplicate = AdvertisingCampaignCreative(
            campaign=self.campaign,
            creative=self.creative,
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_eligible_assignments_are_ordered_by_priority_then_weight(self):
        first_creative = self.creative

        second_creative = AdvertisingPlayoutCreative.objects.create(
            name="Second Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            priority=100,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
            is_active=True,
        )

        third_creative = AdvertisingPlayoutCreative.objects.create(
            name="Third Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
            priority=100,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
            is_active=True,
        )

        AdvertisingCampaignCreative.objects.create(
            campaign=self.campaign,
            creative=first_creative,
            priority=20,
            rotation_weight=100,
        )

        AdvertisingCampaignCreative.objects.create(
            campaign=self.campaign,
            creative=second_creative,
            priority=10,
            rotation_weight=50,
        )

        AdvertisingCampaignCreative.objects.create(
            campaign=self.campaign,
            creative=third_creative,
            priority=10,
            rotation_weight=200,
        )

        assignments = (
            advertising_campaign_eligible_creative_assignments(
                campaign=self.campaign,
                moment=self.now,
            )
        )

        self.assertEqual(
            [a.creative_id for a in assignments],
            [
                third_creative.id,
                second_creative.id,
                first_creative.id,
            ],
        )

    def test_multiple_creatives_may_be_authorized_for_one_campaign(self):
        second_creative = AdvertisingPlayoutCreative.objects.create(
            name="Campaign Creative B",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=12,
            priority=100,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
            is_active=True,
        )

        self.make_assignment()

        AdvertisingCampaignCreative.objects.create(
            campaign=self.campaign,
            creative=second_creative,
            rotation_weight=50,
            priority=100,
        )

        assignments = (
            advertising_campaign_eligible_creative_assignments(
                campaign=self.campaign,
                moment=self.now,
            )
        )

        self.assertEqual(len(assignments), 2)

        self.assertEqual(
            {a.creative_id for a in assignments},
            {
                self.creative.id,
                second_creative.id,
            },
        )
