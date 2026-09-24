from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ballot.models import AtlsHottestEvent, EventPromotionOrder


@override_settings(SECURE_SSL_REDIRECT=False)
class EventPromotionRevenueCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.staff = User.objects.create_user(
            username="revenue-command-staff",
            email="revenue-command@example.com",
            password="RevenueTest123!",
            is_staff=True,
        )

        self.client.force_login(self.staff)

        now = timezone.now()

        self.event = AtlsHottestEvent.objects.create(
            title="Revenue Command Test Event",
            organizer_name="Revenue Test Producer",
            organizer_email="producer@example.com",
            venue_name="Revenue Test Venue",
            address="100 Revenue Way",
            city="Atlanta",
            state="GA",
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=10, hours=3),
            description="Revenue Command accounting verification event.",
            status="approved",
        )

        # ---------------------------------------------------------
        # $50 VERIFIED STRIPE PAYMENT
        # This MUST count as collected revenue.
        # ---------------------------------------------------------
        self.verified_paid = EventPromotionOrder.objects.create(
            event=self.event,
            producer_name="Paid Producer",
            producer_email="paid@example.com",
            package="24_hours",
            requested_start=now + timedelta(days=1),
            requested_end=now + timedelta(days=2),
            quoted_amount=Decimal("50.00"),
            status="paid",
            is_complimentary=False,
            stripe_checkout_session_id="cs_test_revenue_paid",
            stripe_payment_intent_id="pi_test_revenue_paid",
            stripe_payment_status="paid",
            paid_at=now,
        )

        # ---------------------------------------------------------
        # $100 COMPLIMENTARY PROMOTION
        # This MUST NOT count as collected revenue.
        # ---------------------------------------------------------
        self.complimentary = EventPromotionOrder.objects.create(
            event=self.event,
            producer_name="Comp Producer",
            producer_email="comp@example.com",
            package="3_days",
            requested_start=now + timedelta(days=3),
            requested_end=now + timedelta(days=6),
            quoted_amount=Decimal("100.00"),
            status="activated",
            is_complimentary=True,
        )

        # ---------------------------------------------------------
        # $75 AWAITING PAYMENT
        # This MUST NOT count as collected revenue.
        # It MUST count as awaiting-payment revenue.
        # ---------------------------------------------------------
        self.awaiting = EventPromotionOrder.objects.create(
            event=self.event,
            producer_name="Awaiting Producer",
            producer_email="awaiting@example.com",
            package="7_days",
            requested_start=now + timedelta(days=7),
            requested_end=now + timedelta(days=14),
            quoted_amount=Decimal("75.00"),
            status="awaiting_payment",
            is_complimentary=False,
        )

    def test_revenue_command_counts_only_verified_collected_money(self):
        response = self.client.get(
            reverse("event_approval_center"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        metrics = response.context["revenue_metrics"]

        self.assertEqual(
            metrics["collected_revenue"],
            Decimal("50.00"),
        )

        self.assertEqual(
            metrics["awaiting_payment_revenue"],
            Decimal("75.00"),
        )

        self.assertEqual(metrics["paid_orders"], 1)
        self.assertEqual(metrics["awaiting_payment_orders"], 1)
        self.assertEqual(metrics["active_promotions"], 1)
        self.assertEqual(metrics["completed_promotions"], 0)
        self.assertEqual(metrics["complimentary_promotions"], 1)
        self.assertEqual(metrics["total_orders"], 3)

    def test_money_board_renders_verified_totals(self):
        response = self.client.get(
            reverse("event_approval_center"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "$50.00")
        self.assertContains(response, "$75.00")
        self.assertContains(response, "Stripe verified")

    def test_unverified_paid_status_does_not_count_as_revenue(self):
        EventPromotionOrder.objects.create(
            event=self.event,
            producer_name="Fake Paid Producer",
            producer_email="fake-paid@example.com",
            package="24_hours",
            requested_start=timezone.now() + timedelta(days=20),
            requested_end=timezone.now() + timedelta(days=21),
            quoted_amount=Decimal("500.00"),
            status="paid",
            is_complimentary=False,

            # Deliberately NOT Stripe verified.
            stripe_payment_status="",
            paid_at=None,
        )

        response = self.client.get(
            reverse("event_approval_center"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        metrics = response.context["revenue_metrics"]

        # The fake $500 "paid" order must not inflate real revenue.
        self.assertEqual(
            metrics["collected_revenue"],
            Decimal("50.00"),
        )

        self.assertEqual(metrics["paid_orders"], 1)
        self.assertEqual(metrics["total_orders"], 4)
