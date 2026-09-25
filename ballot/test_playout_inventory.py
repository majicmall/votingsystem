from datetime import time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from ballot.models import (
    AdvertisingDaypart,
    AdvertisingInventorySchedule,
    AdvertisingPlayoutCreative,
    BillboardAd,
)


class SixSecondInventoryTests(TestCase):

    def test_atomic_slot_is_six_seconds(self):
        self.assertEqual(
            AdvertisingInventorySchedule.SLOT_SECONDS,
            6,
        )

    def test_continuous_capacity_math(self):
        self.assertEqual(
            AdvertisingInventorySchedule.slots_per_minute(),
            10,
        )
        self.assertEqual(
            AdvertisingInventorySchedule.slots_per_hour(),
            600,
        )
        self.assertEqual(
            AdvertisingInventorySchedule.slots_per_day(),
            14400,
        )
        self.assertEqual(
            AdvertisingInventorySchedule.slots_per_week(),
            100800,
        )

    def test_longer_appearances_consume_consecutive_units(self):
        expected = {
            6: 1,
            12: 2,
            18: 3,
            24: 4,
            30: 5,
            60: 10,
        }

        for seconds, slots in expected.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(
                    AdvertisingInventorySchedule
                    .slots_required_for_duration(seconds),
                    slots,
                )

    def test_non_six_second_duration_rejected(self):
        with self.assertRaises(ValueError):
            AdvertisingInventorySchedule \
                .slots_required_for_duration(10)

    def test_creative_validation_rejects_bad_duration(self):
        creative = AdvertisingPlayoutCreative(
            name="Invalid Creative",
            creative_type="paid",
            duration_seconds=10,
        )

        with self.assertRaises(ValidationError):
            creative.full_clean()

    def test_thirty_second_creative_consumes_five_slots(self):
        creative = AdvertisingPlayoutCreative.objects.create(
            name="ATL House Promo",
            creative_type="house",
            duration_seconds=30,
        )

        self.assertEqual(creative.slots_required, 5)

    def test_advertise_here_is_first_class_fallback_type(self):
        creative = AdvertisingPlayoutCreative.objects.create(
            name="Advertise Here",
            creative_type="advertise_here",
            duration_seconds=6,
            priority=1,
        )

        self.assertEqual(
            creative.creative_type,
            AdvertisingPlayoutCreative.TYPE_ADVERTISE_HERE,
        )
        self.assertEqual(creative.slots_required, 1)


class InventoryPricingTests(TestCase):

    def setUp(self):
        self.daypart = AdvertisingDaypart.objects.create(
            name="Morning",
            start_time=time(6, 0),
            end_time=time(10, 0),
        )

        self.placement = (
            BillboardAd.PLACEMENT_CHOICES[0][0]
        )

    def test_dynamic_multiplier_prices_new_inventory(self):
        schedule = AdvertisingInventorySchedule.objects.create(
            placement=self.placement,
            weekday=0,
            daypart=self.daypart,
            base_slot_price=Decimal("0.5000"),
            traffic_multiplier=Decimal("1.5000"),
        )

        self.assertEqual(
            schedule.current_slot_price,
            Decimal("0.75"),
        )

    def test_weekday_schedule_supports_sunday(self):
        schedule = AdvertisingInventorySchedule.objects.create(
            placement=self.placement,
            weekday=6,
            daypart=self.daypart,
            base_slot_price=Decimal("0.2500"),
        )

        self.assertEqual(
            schedule.get_weekday_display(),
            "Sunday",
        )
