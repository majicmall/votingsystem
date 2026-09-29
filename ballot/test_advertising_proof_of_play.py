from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    record_advertising_appearance_play,
    reserve_advertising_appearance,
)


class AdvertisingProofOfPlayTests(TestCase):

    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="Proof Advertiser",
            campaign_name="Proof Campaign",
            contact_name="King Leo",
            email="proof@example.com",
            total_budget=Decimal("500.00"),
            minimum_campaign_spend=Decimal("50.00"),
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="Proof Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=12,
        )

    def reserve(self):
        return reserve_advertising_appearance(
            placement="homepage_top",
            creative=self.creative,
            starts_at=self.now + timedelta(minutes=5),
            locked_slot_price=Decimal("1.2500"),
            campaign=self.campaign,
        )

    def test_records_complete_appearance_as_played(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id
        played_at = self.now + timedelta(minutes=5)

        result = record_advertising_appearance_play(
            appearance_id=appearance_id,
            played_at=played_at,
        )

        self.assertTrue(result["recorded"])
        self.assertEqual(result["reason"], "played")
        self.assertEqual(result["slot_count"], 2)

        rows = list(
            AdvertisingPlayoutReservation.objects
            .filter(appearance_id=appearance_id)
            .order_by("sequence_number")
        )

        self.assertEqual(len(rows), 2)

        for row in rows:
            self.assertEqual(
                row.status,
                AdvertisingPlayoutReservation.STATUS_PLAYED,
            )
            self.assertEqual(row.played_at, played_at)

    def test_duplicate_recording_is_idempotent(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id
        played_at = self.now + timedelta(minutes=5)

        first = record_advertising_appearance_play(
            appearance_id=appearance_id,
            played_at=played_at,
        )

        second = record_advertising_appearance_play(
            appearance_id=appearance_id,
            played_at=played_at + timedelta(seconds=20),
        )

        self.assertTrue(first["recorded"])
        self.assertFalse(second["recorded"])
        self.assertEqual(second["reason"], "already_played")
        self.assertEqual(second["played_at"], played_at)

    def test_unknown_appearance_is_rejected(self):
        import uuid

        with self.assertRaises(ValidationError):
            record_advertising_appearance_play(
                appearance_id=uuid.uuid4(),
                played_at=self.now,
            )

    def test_cancelled_appearance_cannot_be_played(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id

        AdvertisingPlayoutReservation.objects.filter(
            appearance_id=appearance_id
        ).update(
            status=AdvertisingPlayoutReservation.STATUS_CANCELLED
        )

        with self.assertRaises(ValidationError):
            record_advertising_appearance_play(
                appearance_id=appearance_id,
                played_at=self.now,
            )

    def test_mixed_state_appearance_cannot_be_played(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id

        AdvertisingPlayoutReservation.objects.filter(
            pk=reservations[0].pk
        ).update(
            status=AdvertisingPlayoutReservation.STATUS_MISSED
        )

        with self.assertRaises(ValidationError):
            record_advertising_appearance_play(
                appearance_id=appearance_id,
                played_at=self.now,
            )

    def test_incomplete_appearance_cannot_be_played(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id

        AdvertisingPlayoutReservation.objects.filter(
            pk=reservations[-1].pk
        ).delete()

        with self.assertRaises(ValidationError):
            record_advertising_appearance_play(
                appearance_id=appearance_id,
                played_at=self.now,
            )

    def test_all_slots_receive_identical_proof_timestamp(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id
        played_at = self.now + timedelta(minutes=7)

        record_advertising_appearance_play(
            appearance_id=appearance_id,
            played_at=played_at,
        )

        timestamps = set(
            AdvertisingPlayoutReservation.objects
            .filter(appearance_id=appearance_id)
            .values_list("played_at", flat=True)
        )

        self.assertEqual(timestamps, {played_at})
