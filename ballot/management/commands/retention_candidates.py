"""
ATL's Hottest — Policy-Aware Retention Candidate Report
========================================================

READ-ONLY.

This command identifies records that WOULD qualify under the locked
retention policy. It never deletes, anonymizes, archives, clears,
or modifies database records or files.

Policy version: 2026-09-v1

IMPORTANT:
Vote and NominationLedger retention depend on an awards-cycle boundary.
Those models do not currently provide a verified direct cycle relationship,
so this command deliberately refuses to infer one from created_at.

Financial records are report-only unless/until a separate approved
financial/accounting/legal retention period is established.
"""

from datetime import timedelta

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from ballot.data_retention import (
    POLICY_VERSION,
    get_field_retention_rules,
    get_retention_rules,
)


MAX_SAMPLE_PKS = 10


# Models whose lifecycle anchor can currently be calculated safely
# from verified fields.
LIFECYCLE_RULES = {
    "ballot.SelfNominationCheckIn": {
        "days": 365,
        "description": "365 days after final disposition",
        "selector": "checkin_final_disposition",
    },
    "ballot.AtlsHottestEvent": {
        "days": 730,
        "description": "730 days after event completion",
        "selector": "event_completion",
    },
    "ballot.AdvertisingInquiry": {
        "days": 365,
        "description": "365 days after stale/unconverted inquiry activity",
        "selector": "advertising_inquiry",
    },
    "ballot.Nominee": {
        "days": None,
        "description": "existing explicit nominee archive/deleted_at process",
        "selector": "nominee_archive",
    },
}


# Models intentionally blocked from automatic lifecycle selection.
BLOCKED_AUTOMATIC_MODELS = {
    "ballot.Vote": (
        "Requires the applicable awards-cycle end for voter-email "
        "anonymization and voting-close timestamp for IP/user-agent "
        "clearing. No direct verified cycle relationship is currently "
        "available on Vote."
    ),
    "ballot.NominationLedger": (
        "Requires the applicable awards-cycle end. No direct verified "
        "cycle relationship is currently available on NominationLedger."
    ),
    "ballot.AdvertisingCampaign": (
        "Archive lifecycle requires an explicit campaign-state rule. "
        "No automatic archive selector is approved yet."
    ),
    "ballot.BillboardAdEvent": (
        "Policy treatment is RETAIN. No automatic record-level retention "
        "action is enabled."
    ),
    "ballot.EventPromotionOrder": (
        "Financial/accounting/legal retention period remains intentionally "
        "unassigned. No automatic action is permitted."
    ),
}


ACCOUNT_MANAGED_MODELS = {
    "auth.User",
    "ballot.AssociationProfile",
    "ballot.AssociationMembership",
    "ballot.NominationCategoryRequest",
    "ballot.UserMembership",
}


def model_field_names(model):
    return {field.name for field in model._meta.get_fields()}


def require_fields(model, model_label, fields):
    available = model_field_names(model)
    missing = [field for field in fields if field not in available]

    if missing:
        raise CommandError(
            f"{model_label}: required lifecycle field(s) missing: "
            + ", ".join(missing)
        )


def cutoff_for(days):
    return timezone.now() - timedelta(days=days)


def sample_pks(queryset):
    return list(
        queryset.order_by("pk").values_list("pk", flat=True)[:MAX_SAMPLE_PKS]
    )


def print_samples(command, queryset):
    samples = sample_pks(queryset)

    command.stdout.write(
        "SAMPLE PKs:  "
        + (
            ", ".join(str(pk) for pk in samples)
            if samples
            else "none"
        )
    )


def checkin_candidates(model):
    """
    Final disposition = approved_at OR denied_at.

    reviewed_at alone is not considered final disposition because a record
    may be reviewed without having reached approval or denial.
    """
    require_fields(
        model,
        "ballot.SelfNominationCheckIn",
        [
            "status",
            "submitted_at",
            "approved_at",
            "denied_at",
        ],
    )

    cutoff = cutoff_for(365)

    return model.objects.filter(
        Q(approved_at__isnull=False, approved_at__lte=cutoff)
        | Q(denied_at__isnull=False, denied_at__lte=cutoff)
    )


def event_candidates(model):
    """
    Event completion is anchored to ends_at.

    No fallback to updated_at is allowed because editing an event is not
    equivalent to the event completing.
    """
    require_fields(
        model,
        "ballot.AtlsHottestEvent",
        ["ends_at"],
    )

    cutoff = cutoff_for(730)

    return model.objects.filter(
        ends_at__isnull=False,
        ends_at__lte=cutoff,
    )


def advertising_inquiry_candidates(model):
    """
    Select stale, unconverted advertising inquiries.

    A candidate must satisfy ALL of these conditions:

      * last_activity_at exists
      * last_activity_at is at least 365 days old
      * converted_campaign is NULL
      * converted_at is NULL

    Historical records whose last_activity_at is NULL are deliberately
    excluded. We do not infer or fabricate their activity history from
    created_at.

    is_contacted is workflow state, not conversion state, so it does not
    determine retention eligibility.
    """
    require_fields(
        model,
        "ballot.AdvertisingInquiry",
        [
            "last_activity_at",
            "converted_campaign",
            "converted_at",
            "is_contacted",
        ],
    )

    cutoff = cutoff_for(365)

    return model.objects.filter(
        last_activity_at__isnull=False,
        last_activity_at__lte=cutoff,
        converted_campaign__isnull=True,
        converted_at__isnull=True,
    )


def nominee_candidates(model):
    """
    Existing nominee archival architecture.

    Only records already carrying deleted_at are reported.
    This command does NOT decide that an active nominee should be archived.
    """
    require_fields(
        model,
        "ballot.Nominee",
        ["deleted_at"],
    )

    return model.objects.filter(deleted_at__isnull=False)


class Command(BaseCommand):
    help = (
        "Report policy-aware ATL's Hottest retention candidates. "
        "READ-ONLY: no records or files are modified."
    )

    def handle(self, *args, **options):
        errors = []
        total_candidates = 0

        self.stdout.write("")
        self.stdout.write("=" * 78)
        self.stdout.write(
            " ATL'S HOTTEST — POLICY-AWARE RETENTION CANDIDATE REPORT"
        )
        self.stdout.write("=" * 78)
        self.stdout.write(f" POLICY VERSION: {POLICY_VERSION}")
        self.stdout.write(" MODE: READ-ONLY")
        self.stdout.write(" EXECUTION: DISABLED")
        self.stdout.write(
            f" REPORT TIME: {timezone.localtime().isoformat()}"
        )
        self.stdout.write("")

        rules = {rule.model: rule for rule in get_retention_rules()}

        for model_label, rule in rules.items():
            self.stdout.write("-" * 78)
            self.stdout.write(f"MODEL:      {model_label}")
            self.stdout.write(f"TREATMENT:  {rule.treatment}")

            try:
                app_label, model_name = model_label.split(".", 1)
                model = apps.get_model(app_label, model_name)
            except Exception as exc:
                errors.append(f"{model_label}: model lookup failed: {exc}")
                self.stdout.write(
                    self.style.ERROR(
                        f"STATUS:     MODEL LOOKUP FAILED: {exc}"
                    )
                )
                self.stdout.write("")
                continue

            self.stdout.write(
                f"RECORDS:    {model.objects.count()}"
            )

            if model_label in ACCOUNT_MANAGED_MODELS:
                self.stdout.write(
                    "STATUS:     ACCOUNT-DELETION MANAGED"
                )
                self.stdout.write(
                    "ANCHOR:     verified account deletion request"
                )
                self.stdout.write(
                    "CANDIDATES: not selected by scheduled retention"
                )
                self.stdout.write("")
                continue

            if model_label in BLOCKED_AUTOMATIC_MODELS:
                self.stdout.write(
                    self.style.WARNING(
                        "STATUS:     AUTOMATIC SELECTION BLOCKED"
                    )
                )
                self.stdout.write(
                    f"REASON:     {BLOCKED_AUTOMATIC_MODELS[model_label]}"
                )

                if model_label == "ballot.Vote":
                    field_rules = get_field_retention_rules()

                    for field_name, field_rule in field_rules.items():
                        if field_name.startswith("ballot.Vote."):
                            self.stdout.write(
                                f"FIELD RULE: {field_name} -> "
                                f"{field_rule['action']} after "
                                f"{field_rule['days']} days from "
                                f"{field_rule['anchor']}"
                            )

                self.stdout.write(
                    "CANDIDATES: not calculated"
                )
                self.stdout.write("")
                continue

            lifecycle = LIFECYCLE_RULES.get(model_label)

            if lifecycle is None:
                self.stdout.write(
                    self.style.WARNING(
                        "STATUS:     NO EXECUTABLE LIFECYCLE SELECTOR"
                    )
                )
                self.stdout.write(
                    "CANDIDATES: not calculated"
                )
                self.stdout.write("")
                continue

            selector = lifecycle["selector"]

            try:
                if selector == "checkin_final_disposition":
                    queryset = checkin_candidates(model)

                    self.stdout.write(
                        "STATUS:     LIFECYCLE SELECTOR ACTIVE"
                    )
                    self.stdout.write(
                        "ANCHOR:     approved_at OR denied_at"
                    )
                    self.stdout.write(
                        "PERIOD:     365 days after final disposition"
                    )
                    self.stdout.write(
                        f"CANDIDATES: {queryset.count()}"
                    )
                    print_samples(self, queryset)
                    total_candidates += queryset.count()

                elif selector == "event_completion":
                    queryset = event_candidates(model)

                    self.stdout.write(
                        "STATUS:     LIFECYCLE SELECTOR ACTIVE"
                    )
                    self.stdout.write(
                        "ANCHOR:     ends_at"
                    )
                    self.stdout.write(
                        "PERIOD:     730 days after event completion"
                    )
                    self.stdout.write(
                        f"CANDIDATES: {queryset.count()}"
                    )
                    print_samples(self, queryset)
                    total_candidates += queryset.count()

                elif selector == "advertising_inquiry":
                    queryset = advertising_inquiry_candidates(model)

                    self.stdout.write(
                        "STATUS:     LIFECYCLE SELECTOR ACTIVE"
                    )
                    self.stdout.write(
                        "ANCHOR:     last_activity_at"
                    )
                    self.stdout.write(
                        "PERIOD:     365 days after last activity"
                    )
                    self.stdout.write(
                        "STATE:      converted_campaign IS NULL "
                        "AND converted_at IS NULL"
                    )
                    self.stdout.write(
                        "NULL RULE:  historical NULL activity excluded"
                    )
                    self.stdout.write(
                        f"CANDIDATES: {queryset.count()}"
                    )
                    print_samples(self, queryset)
                    total_candidates += queryset.count()

                elif selector == "nominee_archive":
                    queryset = nominee_candidates(model)

                    self.stdout.write(
                        "STATUS:     EXISTING ARCHIVE STATE"
                    )
                    self.stdout.write(
                        "ANCHOR:     deleted_at is populated"
                    )
                    self.stdout.write(
                        "PERIOD:     no automatic age threshold"
                    )
                    self.stdout.write(
                        f"CANDIDATES: {queryset.count()}"
                    )
                    print_samples(self, queryset)

                else:
                    raise CommandError(
                        f"{model_label}: unknown selector {selector}"
                    )

            except (
                CommandError,
                FieldDoesNotExist,
                TypeError,
                ValueError,
            ) as exc:
                errors.append(f"{model_label}: {exc}")
                self.stdout.write(
                    self.style.ERROR(
                        f"STATUS:     SELECTOR ERROR: {exc}"
                    )
                )

            self.stdout.write("")

        self.stdout.write("=" * 78)
        self.stdout.write(
            f" TOTAL ACTIONABLE TEST CANDIDATES: {total_candidates}"
        )
        self.stdout.write(
            " NO DATABASE RECORDS OR FILES WERE MODIFIED"
        )
        self.stdout.write(
            " EXECUTION REMAINS DISABLED"
        )
        self.stdout.write("=" * 78)

        if errors:
            self.stdout.write("")
            for error in errors:
                self.stdout.write(
                    self.style.ERROR(f"ERROR: {error}")
                )

            raise CommandError(
                "Lifecycle candidate report contains invalid selectors."
            )

        self.stdout.write(
            self.style.SUCCESS(
                " LIFECYCLE CANDIDATE ENGINE: VALIDATED"
            )
        )
