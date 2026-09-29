from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    BillboardAd,
)
from ballot.templatetags.billboard_ads import render_billboard


class AdvertisingLiveDeliverySelectorTests(TestCase):

    def setUp(self):
        self.placement = BillboardAd.PLACEMENT_HOMEPAGE_TOP
        self.now = timezone.now()

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="009 Live Advertiser",
            campaign_name="009 Live Delivery Campaign",
            email="live009@example.com",
            total_budget="500.00",
            minimum_campaign_spend="50.00",
        )

        self.ambe_ad = BillboardAd.objects.create(
            campaign=self.campaign,
            advertiser_name="009 Live Advertiser",
            title="AMBE Scheduled Billboard",
            placement=self.placement,
            destination_url="https://example.com/ambe/",
            call_to_action="Visit Now",
            allocated_budget="500.00",
            minimum_spend="50.00",
            is_active=True,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="009 Live Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            billboard_ad=self.ambe_ad,
            duration_seconds=6,
            is_active=True,
        )

    def create_current_reservation(self):
        return AdvertisingPlayoutReservation.objects.create(
            placement=self.placement,
            creative=self.creative,
            campaign=self.campaign,
            source_type=AdvertisingPlayoutReservation.SOURCE_PAID,
            slot_start=self.now - timedelta(seconds=1),
            slot_end=self.now + timedelta(seconds=5),
            sequence_number=1,
            appearance_slot_count=1,
            locked_slot_price="1.0000",
            status=AdvertisingPlayoutReservation.STATUS_RESERVED,
        )

    def test_current_ambe_reservation_wins_over_normal_rotation(self):
        normal_ad = BillboardAd.objects.create(
            advertiser_name="Normal Rotation",
            title="Normal Rotation Billboard",
            placement=self.placement,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
            is_active=True,
        )

        reservation = self.create_current_reservation()

        result = render_billboard(self.placement)

        self.assertEqual(result["billboard_mode"], "ambe")
        self.assertEqual(result["ad"].pk, self.ambe_ad.pk)
        self.assertNotEqual(result["ad"].pk, normal_ad.pk)
        self.assertEqual(
            result["ambe_appearance_id"],
            reservation.appearance_id,
        )

    def test_future_reservation_does_not_take_over_early(self):
        AdvertisingPlayoutReservation.objects.create(
            placement=self.placement,
            creative=self.creative,
            campaign=self.campaign,
            source_type=AdvertisingPlayoutReservation.SOURCE_PAID,
            slot_start=self.now + timedelta(minutes=5),
            slot_end=self.now + timedelta(minutes=5, seconds=6),
            sequence_number=1,
            appearance_slot_count=1,
            locked_slot_price="1.0000",
            status=AdvertisingPlayoutReservation.STATUS_RESERVED,
        )

        normal_ad = BillboardAd.objects.create(
            advertiser_name="Normal Rotation",
            title="Normal Rotation Billboard",
            placement=self.placement,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
            is_active=True,
        )

        result = render_billboard(self.placement)

        self.assertEqual(result["billboard_mode"], "rotation")
        self.assertEqual(result["ad"].pk, normal_ad.pk)

    def test_played_reservation_is_not_selected_again(self):
        reservation = self.create_current_reservation()
        reservation.status = AdvertisingPlayoutReservation.STATUS_PLAYED
        reservation.played_at = self.now
        reservation.save(update_fields=["status", "played_at"])

        normal_ad = BillboardAd.objects.create(
            advertiser_name="Normal Rotation",
            title="Normal Rotation Billboard",
            placement=self.placement,
            purchase_type=BillboardAd.PURCHASE_ROTATION,
            is_active=True,
        )

        result = render_billboard(self.placement)

        self.assertEqual(result["billboard_mode"], "rotation")
        self.assertEqual(result["ad"].pk, normal_ad.pk)

    def test_exclusive_takeover_remains_above_ambe(self):
        self.create_current_reservation()

        exclusive = BillboardAd.objects.create(
            advertiser_name="Exclusive Advertiser",
            title="Exclusive Billboard",
            placement=self.placement,
            purchase_type=BillboardAd.PURCHASE_EXCLUSIVE,
            is_active=True,
        )

        result = render_billboard(self.placement)

        self.assertEqual(result["billboard_mode"], "exclusive")
        self.assertEqual(result["ad"].pk, exclusive.pk)

    def test_ambe_selection_does_not_mark_proof_of_play(self):
        reservation = self.create_current_reservation()

        result = render_billboard(self.placement)

        self.assertEqual(result["billboard_mode"], "ambe")

        reservation.refresh_from_db()

        self.assertEqual(
            reservation.status,
            AdvertisingPlayoutReservation.STATUS_RESERVED,
        )
        self.assertIsNone(reservation.played_at)

    def test_expired_slot_is_not_selected(self):
        AdvertisingPlayoutReservation.objects.create(
            placement=self.placement,
            creative=self.creative,
            campaign=self.campaign,
            source_type=AdvertisingPlayoutReservation.SOURCE_PAID,
            slot_start=self.now - timedelta(seconds=12),
            slot_end=self.now - timedelta(seconds=6),
            sequence_number=1,
            appearance_slot_count=1,
            locked_slot_price="1.0000",
            status=AdvertisingPlayoutReservation.STATUS_RESERVED,
        )

        result = render_billboard(self.placement)

        self.assertNotEqual(result["billboard_mode"], "ambe")
