"""
Production entry point for the autonomous ATL's Hottest advertising shopper.

IMPORTANT:
    This command MUST enter through the H3B-4A guarded runner.
    It must never call the unguarded H3B-3C runner directly.

Typical scheduler invocation:

    python manage.py run_advertising_shopper

Optional controls:

    python manage.py run_advertising_shopper \
        --lookahead-minutes 60 \
        --campaign-limit 25 \
        --lease-seconds 300
"""

from django.core.management.base import BaseCommand, CommandError

from ballot.models import (
    run_guarded_autonomous_advertising_shopping_pass,
)


class Command(BaseCommand):
    help = (
        "Run one concurrency-protected autonomous advertising "
        "shopping pass."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--lookahead-minutes",
            type=int,
            default=60,
            help=(
                "Number of minutes of future advertising inventory "
                "the autonomous shopper may inspect. Default: 60."
            ),
        )

        parser.add_argument(
            "--campaign-limit",
            type=int,
            default=None,
            help=(
                "Optional maximum number of active campaigns to process "
                "during this execution."
            ),
        )

        parser.add_argument(
            "--lease-seconds",
            type=int,
            default=300,
            help=(
                "Concurrency-lock lease duration in seconds. "
                "Default: 300."
            ),
        )

    def handle(self, *args, **options):
        lookahead_minutes = options["lookahead_minutes"]
        campaign_limit = options["campaign_limit"]
        lease_seconds = options["lease_seconds"]

        if lookahead_minutes < 1:
            raise CommandError(
                "--lookahead-minutes must be at least 1."
            )

        if campaign_limit is not None and campaign_limit < 1:
            raise CommandError(
                "--campaign-limit must be at least 1 when supplied."
            )

        if lease_seconds < 1:
            raise CommandError(
                "--lease-seconds must be at least 1."
            )

        result = run_guarded_autonomous_advertising_shopping_pass(
            lookahead_minutes=lookahead_minutes,
            campaign_limit=campaign_limit,
            lease_seconds=lease_seconds,
        )

        if not isinstance(result, dict):
            raise CommandError(
                "Advertising shopper returned an invalid result."
            )

        executed = result.get("executed")
        reason = result.get("reason")
        execution = result.get("execution")
        runner_result = result.get("runner_result")

        # ---------------------------------------------------------
        # H3B-4A LOCK CONTENTION
        # ---------------------------------------------------------
        if executed is False:
            if reason == "runner_lock_unavailable":
                execution_id = getattr(
                    execution,
                    "execution_id",
                    None,
                )

                self.stdout.write(
                    self.style.WARNING(
                        "Advertising shopper skipped safely: "
                        "runner lock unavailable."
                    )
                )

                if execution_id:
                    self.stdout.write(
                        f"Execution ID: {execution_id}"
                    )

                return

            raise CommandError(
                "Advertising shopper did not execute: "
                f"{reason or 'unknown reason'}"
            )

        # ---------------------------------------------------------
        # SUCCESS CONTRACT VALIDATION
        # ---------------------------------------------------------
        if executed is not True:
            raise CommandError(
                "Advertising shopper returned an invalid "
                "execution state."
            )

        if reason != "completed":
            raise CommandError(
                "Advertising shopper returned an unexpected "
                f"completion reason: {reason!r}."
            )

        if execution is None:
            raise CommandError(
                "Advertising shopper completed without an "
                "execution ledger record."
            )

        if not isinstance(runner_result, dict):
            raise CommandError(
                "Advertising shopper completed without a valid "
                "runner result."
            )

        required_counts = (
            "processed_count",
            "purchased_count",
            "skipped_count",
            "failed_count",
        )

        missing = [
            key
            for key in required_counts
            if key not in runner_result
        ]

        if missing:
            raise CommandError(
                "Advertising shopper runner result is missing: "
                + ", ".join(missing)
            )

        processed_count = runner_result["processed_count"]
        purchased_count = runner_result["purchased_count"]
        skipped_count = runner_result["skipped_count"]
        failed_count = runner_result["failed_count"]

        execution_id = getattr(
            execution,
            "execution_id",
            None,
        )

        execution_status = getattr(
            execution,
            "status",
            None,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Advertising shopper completed successfully."
            )
        )

        if execution_id:
            self.stdout.write(
                f"Execution ID: {execution_id}"
            )

        if execution_status:
            self.stdout.write(
                f"Execution status: {execution_status}"
            )

        self.stdout.write(
            f"Campaigns processed: {processed_count}"
        )
        self.stdout.write(
            f"Appearances purchased: {purchased_count}"
        )
        self.stdout.write(
            f"Campaigns skipped: {skipped_count}"
        )
        self.stdout.write(
            f"Campaigns failed: {failed_count}"
        )
