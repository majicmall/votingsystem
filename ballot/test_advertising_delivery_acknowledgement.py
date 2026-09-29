import json
from datetime import timedelta
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    reserve_advertising_appearance,
)
from ballot.views import acknowledge_advertising_play


class AdvertisingDeliveryAcknowledgementTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.now = timezone.now().replace(microsecond=0)

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="A2D Advertiser",
            campaign_name="A2D Delivery Campaign",
            contact_name="King Leo",
            email="a2d@example.com",
            total_budget=Decimal("500.00"),
            minimum_campaign_spend=Decimal("50.00"),
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=1),
        )

        self.creative = AdvertisingPlayoutCreative.objects.create(
            name="A2D Creative",
            creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            duration_seconds=6,
        )

    def reserve(self, placement="homepage_top"):
        return reserve_advertising_appearance(
            placement=placement,
            creative=self.creative,
            starts_at=self.now,
            locked_slot_price=Decimal("1.0000"),
            campaign=self.campaign,
        )

    def post(self, payload):
        request = self.factory.post(
            "/advertising/play/acknowledge/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return acknowledge_advertising_play(request)

    def body(self, response):
        return json.loads(response.content.decode("utf-8"))

    def test_valid_acknowledgement_records_proof_of_play(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id

        response = self.post({
            "appearance_id": str(appearance_id),
            "placement": "homepage_top",
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["recorded"])
        self.assertEqual(body["reason"], "played")

        reservation = AdvertisingPlayoutReservation.objects.get(
            pk=reservations[0].pk
        )

        self.assertEqual(
            reservation.status,
            AdvertisingPlayoutReservation.STATUS_PLAYED,
        )
        self.assertIsNotNone(reservation.played_at)

    def test_duplicate_acknowledgement_is_idempotent(self):
        reservations = self.reserve()
        appearance_id = reservations[0].appearance_id

        first = self.post({
            "appearance_id": str(appearance_id),
            "placement": "homepage_top",
        })

        first_body = self.body(first)

        second = self.post({
            "appearance_id": str(appearance_id),
            "placement": "homepage_top",
        })

        second_body = self.body(second)

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first_body["recorded"])

        self.assertEqual(second.status_code, 200)
        self.assertFalse(second_body["recorded"])
        self.assertEqual(
            second_body["reason"],
            "already_played",
        )

    def test_unknown_appearance_is_rejected(self):
        import uuid

        response = self.post({
            "appearance_id": str(uuid.uuid4()),
            "placement": "homepage_top",
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "unknown_appearance")

    def test_invalid_uuid_is_rejected(self):
        response = self.post({
            "appearance_id": "not-a-real-uuid",
            "placement": "homepage_top",
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            body["reason"],
            "invalid_appearance_id",
        )

    def test_placement_mismatch_is_rejected(self):
        reservations = self.reserve("homepage_top")

        response = self.post({
            "appearance_id": str(
                reservations[0].appearance_id
            ),
            "placement": "events_top",
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            body["reason"],
            "placement_mismatch",
        )

        reservation = AdvertisingPlayoutReservation.objects.get(
            pk=reservations[0].pk
        )

        self.assertEqual(
            reservation.status,
            AdvertisingPlayoutReservation.STATUS_RESERVED,
        )
        self.assertIsNone(reservation.played_at)

    def test_missing_appearance_id_is_rejected(self):
        response = self.post({
            "placement": "homepage_top",
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            body["reason"],
            "appearance_id_required",
        )

    def test_missing_placement_is_rejected(self):
        reservations = self.reserve()

        response = self.post({
            "appearance_id": str(
                reservations[0].appearance_id
            ),
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            body["reason"],
            "placement_required",
        )

    def test_cancelled_appearance_is_rejected(self):
        reservations = self.reserve()

        AdvertisingPlayoutReservation.objects.filter(
            appearance_id=reservations[0].appearance_id
        ).update(
            status=AdvertisingPlayoutReservation.STATUS_CANCELLED
        )

        response = self.post({
            "appearance_id": str(
                reservations[0].appearance_id
            ),
            "placement": "homepage_top",
        })

        body = self.body(response)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "play_rejected")


class AdvertisingDeliveryAcknowledgementRouteTests(TestCase):

    def test_acknowledgement_route_resolves(self):
        from django.urls import resolve, reverse

        url = reverse("acknowledge_advertising_play")

        self.assertEqual(
            url,
            "/advertise/play/acknowledge/",
        )

        match = resolve(url)

        self.assertEqual(
            match.func,
            acknowledge_advertising_play,
        )

    def test_acknowledgement_route_rejects_get(self):
        response = self.client.get(
            "/advertise/play/acknowledge/"
        )

        self.assertEqual(response.status_code, 405)
