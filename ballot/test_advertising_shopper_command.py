from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


COMMAND_TARGET = (
    "ballot.management.commands.run_advertising_shopper."
    "run_guarded_autonomous_advertising_shopping_pass"
)


class AdvertisingShopperManagementCommandTests(SimpleTestCase):

    def run_command(self, *args):
        stdout = StringIO()

        call_command(
            "run_advertising_shopper",
            *args,
            stdout=stdout,
        )

        return stdout.getvalue()

    def completed_result(
        self,
        *,
        processed=5,
        purchased=2,
        skipped=2,
        failed=1,
    ):
        execution = SimpleNamespace(
            execution_id=uuid.uuid4(),
            status="completed",
        )

        return {
            "executed": True,
            "reason": "completed",
            "execution": execution,
            "runner_result": {
                "processed_count": processed,
                "purchased_count": purchased,
                "skipped_count": skipped,
                "failed_count": failed,
                "campaign_results": [],
            },
        }

    @patch(COMMAND_TARGET)
    def test_command_enters_through_guarded_runner(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = self.completed_result()

        output = self.run_command()

        guarded_runner.assert_called_once_with(
            lookahead_minutes=60,
            campaign_limit=None,
            lease_seconds=300,
        )

        self.assertIn(
            "Advertising shopper completed successfully.",
            output,
        )

    @patch(COMMAND_TARGET)
    def test_command_forwards_custom_controls(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = self.completed_result()

        self.run_command(
            "--lookahead-minutes",
            "90",
            "--campaign-limit",
            "12",
            "--lease-seconds",
            "420",
        )

        guarded_runner.assert_called_once_with(
            lookahead_minutes=90,
            campaign_limit=12,
            lease_seconds=420,
        )

    @patch(COMMAND_TARGET)
    def test_lock_contention_is_safe_skip(
        self,
        guarded_runner,
    ):
        execution = SimpleNamespace(
            execution_id=uuid.uuid4(),
            status="locked_out",
        )

        guarded_runner.return_value = {
            "executed": False,
            "reason": "runner_lock_unavailable",
            "execution": execution,
            "runner_result": None,
        }

        output = self.run_command()

        self.assertIn(
            "Advertising shopper skipped safely:",
            output,
        )

        self.assertIn(
            "runner lock unavailable",
            output,
        )

        self.assertIn(
            str(execution.execution_id),
            output,
        )

    @patch(COMMAND_TARGET)
    def test_success_output_uses_real_runner_counts(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = self.completed_result(
            processed=8,
            purchased=3,
            skipped=4,
            failed=1,
        )

        output = self.run_command()

        self.assertIn(
            "Campaigns processed: 8",
            output,
        )
        self.assertIn(
            "Appearances purchased: 3",
            output,
        )
        self.assertIn(
            "Campaigns skipped: 4",
            output,
        )
        self.assertIn(
            "Campaigns failed: 1",
            output,
        )

    @patch(COMMAND_TARGET)
    def test_execution_identity_is_reported(
        self,
        guarded_runner,
    ):
        result = self.completed_result()

        guarded_runner.return_value = result

        output = self.run_command()

        self.assertIn(
            str(result["execution"].execution_id),
            output,
        )

        self.assertIn(
            "Execution status: completed",
            output,
        )

    @patch(COMMAND_TARGET)
    def test_invalid_top_level_result_fails_closed(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = None

        with self.assertRaises(CommandError):
            self.run_command()

    @patch(COMMAND_TARGET)
    def test_missing_executed_state_fails_closed(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = {
            "reason": "completed",
            "execution": SimpleNamespace(
                execution_id=uuid.uuid4(),
                status="completed",
            ),
            "runner_result": {
                "processed_count": 0,
                "purchased_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
            },
        }

        with self.assertRaises(CommandError):
            self.run_command()

    @patch(COMMAND_TARGET)
    def test_completed_execution_requires_ledger_record(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = {
            "executed": True,
            "reason": "completed",
            "execution": None,
            "runner_result": {
                "processed_count": 0,
                "purchased_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
            },
        }

        with self.assertRaises(CommandError):
            self.run_command()

    @patch(COMMAND_TARGET)
    def test_completed_execution_requires_runner_result(
        self,
        guarded_runner,
    ):
        guarded_runner.return_value = {
            "executed": True,
            "reason": "completed",
            "execution": SimpleNamespace(
                execution_id=uuid.uuid4(),
                status="completed",
            ),
            "runner_result": None,
        }

        with self.assertRaises(CommandError):
            self.run_command()

    @patch(COMMAND_TARGET)
    def test_missing_runner_count_fails_closed(
        self,
        guarded_runner,
    ):
        result = self.completed_result()

        del result["runner_result"]["failed_count"]

        guarded_runner.return_value = result

        with self.assertRaises(CommandError):
            self.run_command()

    def test_zero_lookahead_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "--lookahead-minutes must be at least 1.",
        ):
            self.run_command(
                "--lookahead-minutes",
                "0",
            )

    def test_negative_lookahead_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "--lookahead-minutes must be at least 1.",
        ):
            self.run_command(
                "--lookahead-minutes",
                "-1",
            )

    def test_zero_campaign_limit_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "--campaign-limit must be at least 1 when supplied.",
        ):
            self.run_command(
                "--campaign-limit",
                "0",
            )

    def test_negative_campaign_limit_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "--campaign-limit must be at least 1 when supplied.",
        ):
            self.run_command(
                "--campaign-limit",
                "-1",
            )

    def test_zero_lease_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "--lease-seconds must be at least 1.",
        ):
            self.run_command(
                "--lease-seconds",
                "0",
            )

    def test_negative_lease_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "--lease-seconds must be at least 1.",
        ):
            self.run_command(
                "--lease-seconds",
                "-1",
            )
