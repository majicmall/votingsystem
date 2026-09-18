"""
ATL's Hottest — Retention Anonymization Blueprint
==================================================

READ-ONLY policy definitions.

This module describes which personal fields may eventually be anonymized.
It does NOT modify database records.

No destructive retention processing should be enabled until:
1. retention periods are approved,
2. field transformations are reviewed,
3. dry-run selection logic is tested,
4. production backups/recovery procedures are confirmed.
"""

from dataclasses import dataclass


CLEAR = "CLEAR"
UNIQUE_EMAIL = "UNIQUE_EMAIL"
REDACT_TEXT = "REDACT_TEXT"
DELETE_FILE = "DELETE_FILE"
PRESERVE = "PRESERVE"


@dataclass(frozen=True)
class FieldAnonymization:
    field: str
    action: str
    reason: str


@dataclass(frozen=True)
class ModelAnonymization:
    model: str
    fields: tuple[FieldAnonymization, ...]
    notes: str = ""


ANONYMIZATION_BLUEPRINTS = (

    # -----------------------------------------------------
    # VOTING
    # -----------------------------------------------------

    ModelAnonymization(
        model="ballot.Vote",
        fields=(
            FieldAnonymization(
                field="email",
                action=UNIQUE_EMAIL,
                reason=(
                    "Remove the voter's email identity while preserving "
                    "the vote/category/nominee historical record and "
                    "avoiding collisions with the unique voting constraint."
                ),
            ),
            FieldAnonymization(
                field="ip_address",
                action=CLEAR,
                reason=(
                    "Remove network identifier after the approved "
                    "ballot-integrity/security retention period."
                ),
            ),
            FieldAnonymization(
                field="user_agent",
                action=CLEAR,
                reason=(
                    "Remove device/browser metadata after the approved "
                    "security and audit period."
                ),
            ),
            FieldAnonymization(
                field="category",
                action=PRESERVE,
                reason="Required for historical ballot/results integrity.",
            ),
            FieldAnonymization(
                field="nominee",
                action=PRESERVE,
                reason="Required for historical ballot/results integrity.",
            ),
            FieldAnonymization(
                field="created_at",
                action=PRESERVE,
                reason="Required for ballot chronology and audit history.",
            ),
        ),
        notes=(
            "The future UNIQUE_EMAIL transformation must create a unique, "
            "non-reversible replacement for every retained vote. Do not "
            "replace all voter emails with one shared placeholder."
        ),
    ),

    # -----------------------------------------------------
    # NOMINATION LEDGER
    # -----------------------------------------------------

    ModelAnonymization(
        model="ballot.NominationLedger",
        fields=(
            FieldAnonymization(
                field="nominator_name",
                action=REDACT_TEXT,
                reason=(
                    "Remove the nominator's personal identity after the "
                    "approved nomination-integrity/audit period."
                ),
            ),
            FieldAnonymization(
                field="nominator_email",
                action=UNIQUE_EMAIL,
                reason=(
                    "Remove direct email identity while avoiding collisions "
                    "with nomination uniqueness constraints."
                ),
            ),
            FieldAnonymization(
                field="submitted_nominee_name",
                action=PRESERVE,
                reason="Preserves the historical nomination record.",
            ),
            FieldAnonymization(
                field="nominee",
                action=PRESERVE,
                reason="Preserves the historical nomination relationship.",
            ),
            FieldAnonymization(
                field="category",
                action=PRESERVE,
                reason="Preserves the historical nomination category.",
            ),
            FieldAnonymization(
                field="communications_consent",
                action=PRESERVE,
                reason=(
                    "Consent state is audit evidence and requires separate "
                    "retention/withdrawal treatment."
                ),
            ),
            FieldAnonymization(
                field="communications_consent_at",
                action=PRESERVE,
                reason="Preserves when the consent choice was recorded.",
            ),
            FieldAnonymization(
                field="communications_consent_version",
                action=PRESERVE,
                reason="Preserves which consent language/version applied.",
            ),
            FieldAnonymization(
                field="created_at",
                action=PRESERVE,
                reason="Preserves nomination chronology.",
            ),
        ),
        notes=(
            "Marketing consent evidence must not be treated as permission "
            "to continue marketing after a person withdraws consent. "
            "Subscription/preference state should remain logically separate "
            "from historical consent evidence."
        ),
    ),

    # -----------------------------------------------------
    # SELF-NOMINATION CHECK-IN
    # -----------------------------------------------------

    ModelAnonymization(
        model="ballot.SelfNominationCheckIn",
        fields=(
            FieldAnonymization(
                field="email",
                action=UNIQUE_EMAIL,
                reason="Remove the participant's direct email identity.",
            ),
            FieldAnonymization(
                field="communications_consent",
                action=PRESERVE,
                reason="Historical consent evidence requires separate treatment.",
            ),
            FieldAnonymization(
                field="communications_consent_at",
                action=PRESERVE,
                reason="Preserve consent audit timestamp.",
            ),
            FieldAnonymization(
                field="communications_consent_version",
                action=PRESERVE,
                reason="Preserve consent-language version.",
            ),
        ),
        notes=(
            "Additional Check-In identity/profile fields must be reviewed "
            "against the actual model before executable anonymization is built."
        ),
    ),

    # -----------------------------------------------------
    # ADVERTISING INQUIRIES
    # -----------------------------------------------------

    ModelAnonymization(
        model="ballot.AdvertisingInquiry",
        fields=(
            FieldAnonymization(
                field="contact_name",
                action=REDACT_TEXT,
                reason="Remove unnecessary personal contact identity.",
            ),
            FieldAnonymization(
                field="email",
                action=UNIQUE_EMAIL,
                reason="Remove unnecessary direct email identity.",
            ),
            FieldAnonymization(
                field="phone",
                action=CLEAR,
                reason="Remove unnecessary direct phone contact information.",
            ),
            FieldAnonymization(
                field="creative_upload",
                action=DELETE_FILE,
                reason=(
                    "Remove uploaded creative when the approved inquiry "
                    "retention period has ended and the file is no longer "
                    "needed for an active or historical campaign."
                ),
            ),
        ),
        notes=(
            "Business/campaign information may have a different retention "
            "period from an individual contact person's information."
        ),
    ),
)


def get_anonymization_blueprints():
    return ANONYMIZATION_BLUEPRINTS
