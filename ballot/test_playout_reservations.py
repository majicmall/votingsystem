from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingPlayoutCreative,
    AdvertisingPlayoutReservation,
    BillboardAd,
    reserve_advertising_appearance,
)


class AdvertisingPlayoutReservationTests(TestCase):

    def setUp(self):
        self.placement = (
            BillboardAd.PLACEMENT_CHOICES[0][0]
        )

        self.starts_at = timezone.make_aware(
            datetime(2026, 10, 1, 12, 0, 0)
        )

        self.campaign = AdvertisingCampaign.objects.create(
            advertiser_name="H2 Test Advertiser",
            campaign_name="H2 Reservation Tests",
            total_budget=Decimal("1000.00"),
        )

    def make_creative(self, seconds=6, creative_type="paid"):
        return AdvertisingPlayoutCreative.objects.create(
            name=f"{seconds} Second Creative",
            creative_type=creative_type,
            duration_seconds=seconds,
        )

    def test_six_second_appearance_creates_one_slot(self):
        creative = self.make_creative(6)

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.5000"),
            campaign=self.campaign,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].slot_end - rows[0].slot_start,
            timedelta(seconds=6),
        )

    def test_twelve_second_appearance_creates_two_consecutive_slots(self):
        creative = self.make_creative(12)

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.5000"),
            campaign=self.campaign,
        )

        self.assertEqual(len(rows), 2)

        self.assertEqual(
            rows[1].slot_start,
            rows[0].slot_end,
        )

        self.assertEqual(
            [row.sequence_number for row in rows],
            [1, 2],
        )

        self.assertEqual(
            len({row.appearance_id for row in rows}),
            1,
        )

    def test_thirty_second_appearance_creates_five_slots(self):
        creative = self.make_creative(30)

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.7500"),
            campaign=self.campaign,
        )

        self.assertEqual(len(rows), 5)

        for previous, current in zip(rows, rows[1:]):
            self.assertEqual(
                current.slot_start,
                previous.slot_end,
            )

    def test_locked_price_is_copied_to_every_slot(self):
        creative = self.make_creative(12)

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("1.2500"),
            campaign=self.campaign,
        )

        self.assertTrue(
            all(
                row.locked_slot_price == Decimal("1.2500")
                for row in rows
            )
        )

    def test_same_property_same_timestamp_cannot_double_book(self):
        creative_a = self.make_creative(6)
        creative_b = AdvertisingPlayoutCreative.objects.create(
            name="Second Advertiser",
            creative_type="paid",
            duration_seconds=6,
        )

        reserve_advertising_appearance(
            placement=self.placement,
            creative=creative_a,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.5000"),
            campaign=self.campaign,
        )

        with self.assertRaises(ValidationError):
            reserve_advertising_appearance(
                placement=self.placement,
                creative=creative_b,
                starts_at=self.starts_at,
                locked_slot_price=Decimal("0.5000"),
                campaign=self.campaign,
            )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            1,
        )

    def test_partial_multi_slot_collision_rolls_back_entire_appearance(self):
        blocker = self.make_creative(6)

        reserve_advertising_appearance(
            placement=self.placement,
            creative=blocker,
            starts_at=self.starts_at + timedelta(seconds=6),
            locked_slot_price=Decimal("0.5000"),
            campaign=self.campaign,
        )

        twelve_second = AdvertisingPlayoutCreative.objects.create(
            name="12 Second Advertiser",
            creative_type="paid",
            duration_seconds=12,
        )

        with self.assertRaises(ValidationError):
            reserve_advertising_appearance(
                placement=self.placement,
                creative=twelve_second,
                starts_at=self.starts_at,
                locked_slot_price=Decimal("0.5000"),
                campaign=self.campaign,
            )

        # Only the original blocker survives.
        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            1,
        )

    def test_different_properties_can_use_same_timestamp(self):
        creative = self.make_creative(6)

        placement_a = BillboardAd.PLACEMENT_CHOICES[0][0]
        placement_b = BillboardAd.PLACEMENT_CHOICES[1][0]

        reserve_advertising_appearance(
            placement=placement_a,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.5000"),
            campaign=self.campaign,
        )

        reserve_advertising_appearance(
            placement=placement_b,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.5000"),
            campaign=self.campaign,
        )

        self.assertEqual(
            AdvertisingPlayoutReservation.objects.count(),
            2,
        )

    def test_source_type_matches_creative(self):
        creative = self.make_creative(
            6,
            creative_type="house",
        )

        rows = reserve_advertising_appearance(
            placement=self.placement,
            creative=creative,
            starts_at=self.starts_at,
            locked_slot_price=Decimal("0.0000"),
        )

        self.assertEqual(rows[0].source_type, "house")

    def test_slot_end_must_be_exactly_six_seconds(self):
        creative = self.make_creative(6)

        bad = AdvertisingPlayoutReservation(
            placement=self.placement,
            creative=creative,
            source_type="paid",
            slot_start=self.starts_at,
            slot_end=self.starts_at + timedelta(seconds=12),
            sequence_number=1,
            appearance_slot_count=1,
            locked_slot_price=Decimal("0.5000"),
        )

        with self.assertRaises(ValidationError):
            bad.full_clean()
