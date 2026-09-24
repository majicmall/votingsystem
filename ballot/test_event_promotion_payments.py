import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ballot.models import AtlsHottestEvent, EventPromotionOrder


User = get_user_model()


@override_settings(
    STRIPE_SECRET_KEY="sk_test_008",
    STRIPE_WEBHOOK_SECRET="whsec_test_008",
)
class EventPromotionPaymentSecurityTests(TestCase):
    def setUp(self):
        now = timezone.now()

        self.event = AtlsHottestEvent.objects.create(
            title="Launch 008 Revenue Test Event",
            organizer_name="ATL Test Producer",
            organizer_email="producer@example.com",
            starts_at=now,
            ends_at=now + timezone.timedelta(hours=4),
            description="Revenue security test event.",
            status="approved",
        )

        self.order = EventPromotionOrder.objects.create(
            event=self.event,
            producer_name="ATL Test Producer",
            producer_email="producer@example.com",
            package="24_hours",
            requested_start=now + timezone.timedelta(days=1),
            requested_end=now + timezone.timedelta(days=2),
            quoted_amount=Decimal("50.00"),
            status="awaiting_payment",
            stripe_checkout_session_id="cs_test_launch008",
        )

        self.webhook_url = reverse("stripe_event_promotion_webhook")

    def stripe_event(
        self,
        *,
        payment_status="paid",
        amount_total=5000,
        currency="usd",
        session_id="cs_test_launch008",
        public_token=None,
        order_id=None,
        event_type="checkout.session.completed",
    ):
        return {
            "type": event_type,
            "data": {
                "object": {
                    "id": session_id,
                    "payment_status": payment_status,
                    "amount_total": amount_total,
                    "currency": currency,
                    "payment_intent": "pi_test_launch008",
                    "metadata": {
                        "event_promotion_order_id": str(
                            order_id if order_id is not None else self.order.pk
                        ),
                        "event_promotion_public_token": str(
                            public_token
                            if public_token is not None
                            else self.order.public_token
                        ),
                    },
                }
            },
        }

    def post_verified_webhook(self, stripe_event):
        with patch(
            "ballot.views.stripe.Webhook.construct_event",
            return_value=stripe_event,
        ):
            return self.client.post(
                self.webhook_url,
                data=json.dumps(stripe_event),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="test-signature",
            )

    def test_success_page_does_not_mark_order_paid(self):
        response = self.client.get(
            reverse(
                "event_promotion_payment_success",
                kwargs={"token": self.order.public_token},
            )
        )

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.event.refresh_from_db()

        self.assertEqual(self.order.status, "awaiting_payment")
        self.assertIsNone(self.order.paid_at)
        self.assertFalse(self.event.show_on_homepage)

    def test_unpaid_completed_session_does_not_mark_order_paid(self):
        response = self.post_verified_webhook(
            self.stripe_event(payment_status="unpaid")
        )

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "awaiting_payment")
        self.assertIsNone(self.order.paid_at)

    def test_wrong_currency_is_rejected(self):
        response = self.post_verified_webhook(
            self.stripe_event(currency="eur")
        )

        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "awaiting_payment")
        self.assertIsNone(self.order.paid_at)

    def test_wrong_amount_is_rejected(self):
        response = self.post_verified_webhook(
            self.stripe_event(amount_total=4900)
        )

        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "awaiting_payment")
        self.assertIsNone(self.order.paid_at)

    def test_wrong_checkout_session_is_rejected(self):
        response = self.post_verified_webhook(
            self.stripe_event(session_id="cs_wrong_session")
        )

        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "awaiting_payment")
        self.assertIsNone(self.order.paid_at)

    def test_wrong_public_token_is_rejected(self):
        import uuid

        response = self.post_verified_webhook(
            self.stripe_event(public_token=uuid.uuid4())
        )

        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "awaiting_payment")
        self.assertIsNone(self.order.paid_at)

    def test_valid_verified_payment_records_money_and_activates(self):
        response = self.post_verified_webhook(
            self.stripe_event()
        )

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.event.refresh_from_db()

        self.assertEqual(self.order.status, "activated")
        self.assertEqual(
            self.order.stripe_payment_intent_id,
            "pi_test_launch008",
        )
        self.assertEqual(self.order.stripe_payment_status, "paid")
        self.assertIsNotNone(self.order.paid_at)

        self.assertTrue(self.event.show_on_homepage)
        self.assertEqual(
            self.event.homepage_payment_status,
            "paid",
        )
        self.assertEqual(
            self.event.homepage_amount_paid,
            Decimal("50.00"),
        )
        self.assertEqual(
            self.event.homepage_package,
            "24_hours",
        )

    def test_duplicate_webhook_is_idempotent(self):
        first = self.post_verified_webhook(
            self.stripe_event()
        )
        self.assertEqual(first.status_code, 200)

        self.order.refresh_from_db()
        original_paid_at = self.order.paid_at

        second = self.post_verified_webhook(
            self.stripe_event()
        )

        self.assertEqual(second.status_code, 200)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, "activated")
        self.assertEqual(self.order.paid_at, original_paid_at)


class EventPromotionStaffPaymentTests(TestCase):
    def setUp(self):
        now = timezone.now()

        self.staff = User.objects.create_user(
            username="launch008-staff",
            password="Launch-008-Test-Password!",
            is_staff=True,
        )

        self.event = AtlsHottestEvent.objects.create(
            title="Launch 008 Staff Revenue Test",
            organizer_name="ATL Test Producer",
            organizer_email="producer@example.com",
            starts_at=now,
            ends_at=now + timezone.timedelta(hours=4),
            description="Staff payment control test.",
            status="approved",
        )

        self.client.force_login(self.staff)

    def make_order(self, **overrides):
        data = {
            "event": self.event,
            "producer_name": "ATL Test Producer",
            "producer_email": "producer@example.com",
            "package": "24_hours",
            "requested_start": timezone.now() + timezone.timedelta(days=1),
            "requested_end": timezone.now() + timezone.timedelta(days=2),
            "quoted_amount": Decimal("50.00"),
            "status": "awaiting_payment",
            "is_complimentary": False,
        }
        data.update(overrides)
        return EventPromotionOrder.objects.create(**data)

    def test_staff_cannot_manually_mark_normal_order_paid(self):
        order = self.make_order()

        response = self.client.post(
            reverse(
                "event_promotion_order_action",
                kwargs={"pk": order.pk},
            ),
            {"action": "paid"},
        )

        self.assertEqual(response.status_code, 302)

        order.refresh_from_db()

        self.assertEqual(order.status, "awaiting_payment")
        self.assertIsNone(order.paid_at)

    def test_staff_can_authorize_complimentary_order(self):
        order = self.make_order(
            quoted_amount=Decimal("0.00"),
            is_complimentary=True,
        )

        response = self.client.post(
            reverse(
                "event_promotion_order_action",
                kwargs={"pk": order.pk},
            ),
            {"action": "paid"},
        )

        self.assertEqual(response.status_code, 302)

        order.refresh_from_db()

        self.assertEqual(order.status, "paid")
        self.assertIsNone(order.paid_at)
        self.assertEqual(order.stripe_payment_status, "")
