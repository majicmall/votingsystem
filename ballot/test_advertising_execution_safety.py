from datetime import timedelta
from unittest.mock import patch
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ballot.models import (
    AdvertisingShoppingExecution,
    AdvertisingShoppingRunnerLock,
    acquire_advertising_shopping_runner_lock,
    ensure_advertising_shopping_runner_lock,
    release_advertising_shopping_runner_lock,
    run_guarded_autonomous_advertising_shopping_pass,
)


class AdvertisingExecutionSafetyTests(TestCase):

    def setUp(self):
        self.moment = timezone.now()

    def test_singleton_lock_is_created_once(self):
        first = ensure_advertising_shopping_runner_lock()
        second = ensure_advertising_shopping_runner_lock()

        self.assertEqual(first.pk, second.pk)

        self.assertEqual(
            AdvertisingShoppingRunnerLock.objects.count(),
            1,
        )

    def test_available_lock_can_be_acquired(self):
        token = uuid.uuid4()

        result = acquire_advertising_shopping_runner_lock(
            owner_token=token,
            moment=self.moment,
            lease_seconds=300,
        )

        self.assertTrue(result["acquired"])

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertEqual(lock.owner_token, token)
        self.assertEqual(lock.acquired_at, self.moment)
        self.assertEqual(
            lock.lease_expires_at,
            self.moment + timedelta(seconds=300),
        )

    def test_live_lock_rejects_second_owner(self):
        first_token = uuid.uuid4()
        second_token = uuid.uuid4()

        first = acquire_advertising_shopping_runner_lock(
            owner_token=first_token,
            moment=self.moment,
            lease_seconds=300,
        )

        second = acquire_advertising_shopping_runner_lock(
            owner_token=second_token,
            moment=self.moment + timedelta(seconds=1),
            lease_seconds=300,
        )

        self.assertTrue(first["acquired"])
        self.assertFalse(second["acquired"])

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertEqual(
            lock.owner_token,
            first_token,
        )

    def test_expired_lease_can_be_recovered(self):
        stale_token = uuid.uuid4()
        new_token = uuid.uuid4()

        first = acquire_advertising_shopping_runner_lock(
            owner_token=stale_token,
            moment=self.moment,
            lease_seconds=10,
        )

        recovered = acquire_advertising_shopping_runner_lock(
            owner_token=new_token,
            moment=self.moment + timedelta(seconds=11),
            lease_seconds=300,
        )

        self.assertTrue(first["acquired"])
        self.assertTrue(recovered["acquired"])

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertEqual(
            lock.owner_token,
            new_token,
        )

    def test_wrong_owner_cannot_release_lock(self):
        owner = uuid.uuid4()
        attacker = uuid.uuid4()

        acquire_advertising_shopping_runner_lock(
            owner_token=owner,
            moment=self.moment,
            lease_seconds=300,
        )

        released = release_advertising_shopping_runner_lock(
            owner_token=attacker,
        )

        self.assertFalse(released)

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertEqual(
            lock.owner_token,
            owner,
        )

    def test_correct_owner_can_release_lock(self):
        owner = uuid.uuid4()

        acquire_advertising_shopping_runner_lock(
            owner_token=owner,
            moment=self.moment,
            lease_seconds=300,
        )

        released = release_advertising_shopping_runner_lock(
            owner_token=owner,
        )

        self.assertTrue(released)

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertIsNone(lock.owner_token)
        self.assertIsNone(lock.acquired_at)
        self.assertIsNone(lock.lease_expires_at)

    def test_guarded_pass_records_completed_execution(self):
        fake_result = {
            "moment": self.moment,
            "lookahead_minutes": 60,
            "campaign_limit": None,
            "processed_count": 5,
            "purchased_count": 2,
            "skipped_count": 2,
            "failed_count": 1,
            "campaign_results": [],
        }

        with patch(
            "ballot.models.run_autonomous_advertising_shopping_pass",
            return_value=fake_result,
        ):
            result = run_guarded_autonomous_advertising_shopping_pass(
                moment=self.moment,
                lookahead_minutes=60,
            )

        self.assertTrue(result["executed"])
        self.assertEqual(result["reason"], "completed")

        execution = result["execution"]

        self.assertEqual(
            execution.status,
            AdvertisingShoppingExecution.STATUS_COMPLETED,
        )
        self.assertEqual(execution.processed_count, 5)
        self.assertEqual(execution.purchased_count, 2)
        self.assertEqual(execution.skipped_count, 2)
        self.assertEqual(execution.failed_count, 1)
        self.assertIsNotNone(execution.finished_at)

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertIsNone(lock.owner_token)

    def test_guarded_pass_safely_exits_when_lock_is_held(self):
        existing_owner = uuid.uuid4()

        acquire_advertising_shopping_runner_lock(
            owner_token=existing_owner,
            moment=self.moment,
            lease_seconds=300,
        )

        with patch(
            "ballot.models.run_autonomous_advertising_shopping_pass",
        ) as runner:
            result = run_guarded_autonomous_advertising_shopping_pass(
                moment=self.moment + timedelta(seconds=1),
            )

        runner.assert_not_called()

        self.assertFalse(result["executed"])
        self.assertEqual(
            result["reason"],
            "runner_lock_unavailable",
        )

        execution = result["execution"]

        self.assertEqual(
            execution.status,
            AdvertisingShoppingExecution.STATUS_LOCKED_OUT,
        )

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertEqual(
            lock.owner_token,
            existing_owner,
        )

    def test_runner_exception_is_recorded_and_lock_released(self):
        with patch(
            "ballot.models.run_autonomous_advertising_shopping_pass",
            side_effect=RuntimeError("Intentional runner failure"),
        ):
            with self.assertRaises(RuntimeError):
                run_guarded_autonomous_advertising_shopping_pass(
                    moment=self.moment,
                )

        execution = AdvertisingShoppingExecution.objects.get()

        self.assertEqual(
            execution.status,
            AdvertisingShoppingExecution.STATUS_FAILED,
        )
        self.assertEqual(
            execution.failure_type,
            "RuntimeError",
        )
        self.assertEqual(
            execution.failure_message,
            "Intentional runner failure",
        )
        self.assertIsNotNone(execution.finished_at)

        lock = AdvertisingShoppingRunnerLock.objects.get()

        self.assertIsNone(lock.owner_token)

    def test_execution_id_matches_lock_owner_for_real_execution(self):
        fake_result = {
            "moment": self.moment,
            "lookahead_minutes": 60,
            "campaign_limit": None,
            "processed_count": 0,
            "purchased_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "campaign_results": [],
        }

        with patch(
            "ballot.models.run_autonomous_advertising_shopping_pass",
            return_value=fake_result,
        ):
            result = run_guarded_autonomous_advertising_shopping_pass(
                moment=self.moment,
            )

        execution = result["execution"]

        self.assertIsNotNone(execution.execution_id)

        self.assertEqual(
            AdvertisingShoppingExecution.objects.filter(
                execution_id=execution.execution_id,
            ).count(),
            1,
        )

    def test_invalid_lease_seconds_is_rejected(self):
        for invalid in (0, -1, True, "300"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    acquire_advertising_shopping_runner_lock(
                        owner_token=uuid.uuid4(),
                        moment=self.moment,
                        lease_seconds=invalid,
                    )

    def test_invalid_guard_arguments_are_rejected_before_execution(self):
        invalid_calls = [
            {"lookahead_minutes": 0},
            {"lookahead_minutes": True},
            {"campaign_limit": 0},
            {"campaign_limit": True},
            {"lease_seconds": 0},
            {"lease_seconds": True},
        ]

        for kwargs in invalid_calls:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    run_guarded_autonomous_advertising_shopping_pass(
                        moment=self.moment,
                        **kwargs,
                    )

        self.assertEqual(
            AdvertisingShoppingExecution.objects.count(),
            0,
        )

    def test_execution_summary_math_matches_runner(self):
        fake_result = {
            "moment": self.moment,
            "lookahead_minutes": 10,
            "campaign_limit": 10,
            "processed_count": 7,
            "purchased_count": 3,
            "skipped_count": 3,
            "failed_count": 1,
            "campaign_results": [],
        }

        with patch(
            "ballot.models.run_autonomous_advertising_shopping_pass",
            return_value=fake_result,
        ):
            result = run_guarded_autonomous_advertising_shopping_pass(
                moment=self.moment,
                lookahead_minutes=10,
                campaign_limit=10,
            )

        execution = result["execution"]

        self.assertEqual(
            execution.processed_count,
            (
                execution.purchased_count +
                execution.skipped_count +
                execution.failed_count
            ),
        )
