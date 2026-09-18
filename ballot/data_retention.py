"""
ATL's Hottest — Data Retention Policy
=====================================

Central retention policy.

POLICY VERSION:
    2026-09-v1

IMPORTANT:
These rules define ATL's Hottest operational retention schedule.

This module does NOT itself delete, anonymize, archive, or modify records.

Financial/accounting/legal retention periods remain unassigned until the
applicable requirements are separately confirmed.

Treatments
----------
DELETE:
    Remove the applicable record.

ANONYMIZE:
    Preserve necessary historical/statistical information while removing
    or neutralizing personal identifiers.

ARCHIVE:
    Remove from active/public operation while preserving appropriate history.

RETAIN:
    Preserve under the applicable retention rule.
"""

from dataclasses import dataclass
from typing import Optional


POLICY_VERSION = "2026-09-v1"

DELETE = "DELETE"
ANONYMIZE = "ANONYMIZE"
ARCHIVE = "ARCHIVE"
RETAIN = "RETAIN"


@dataclass(frozen=True)
class RetentionRule:
    model: str
    treatment: str
    purpose: str
    automatic_days: Optional[int] = None
    anchor: str = ""
    notes: str = ""


RETENTION_RULES = (
    RetentionRule(
        model="auth.User",
        treatment=DELETE,
        purpose="ATL's Hottest account identity.",
        automatic_days=None,
        anchor="verified account deletion request",
        notes=(
            "Retained while the account exists. Deleted through the verified "
            "account-deletion workflow. Related account-owned records use "
            "Django CASCADE."
        ),
    ),

    RetentionRule(
        model="ballot.AssociationProfile",
        treatment=DELETE,
        purpose="Association account profile.",
        automatic_days=None,
        anchor="verified account deletion request",
        notes=(
            "Deleted with the owning account. Uploaded profile media is "
            "explicitly removed by the account-deletion workflow."
        ),
    ),

    RetentionRule(
        model="ballot.AssociationMembership",
        treatment=DELETE,
        purpose="Association membership relationship.",
        automatic_days=None,
        anchor="verified account deletion request",
        notes="Deleted with the owning account through CASCADE.",
    ),

    RetentionRule(
        model="ballot.NominationCategoryRequest",
        treatment=DELETE,
        purpose="Account-owned category request.",
        automatic_days=None,
        anchor="verified account deletion request",
        notes="Deleted with the requesting account through CASCADE.",
    ),

    RetentionRule(
        model="ballot.UserMembership",
        treatment=DELETE,
        purpose="Current account membership state.",
        automatic_days=None,
        anchor="verified account deletion request",
        notes=(
            "Account relationship currently uses CASCADE. Independent "
            "transaction records follow their own retention requirements."
        ),
    ),

    RetentionRule(
        model="ballot.Vote",
        treatment=ANONYMIZE,
        purpose="Ballot integrity, audit, dispute handling, and results.",
        automatic_days=365,
        anchor="end of applicable awards cycle",
        notes=(
            "Voter email may be anonymized after the awards cycle plus "
            "12 months. IP address and user-agent use a shorter 90-day "
            "security retention rule after voting closes. Vote, nominee, "
            "category, and appropriate historical result data are preserved."
        ),
    ),

    RetentionRule(
        model="ballot.NominationLedger",
        treatment=ANONYMIZE,
        purpose="Nomination integrity and historical audit record.",
        automatic_days=365,
        anchor="end of applicable awards cycle",
        notes=(
            "Nominator identity may be anonymized after the awards cycle "
            "plus 12 months. Historical nomination information may remain. "
            "Consent evidence follows separate consent/audit treatment."
        ),
    ),

    RetentionRule(
        model="ballot.SelfNominationCheckIn",
        treatment=ANONYMIZE,
        purpose="Check-In review and nomination administration.",
        automatic_days=365,
        anchor="final disposition",
        notes=(
            "Personal identity may be anonymized 12 months after final "
            "disposition. Final disposition means the applicable completed "
            "review outcome, such as approval or denial. Executable logic "
            "must use the appropriate disposition timestamp rather than "
            "submission time when available."
        ),
    ),

    RetentionRule(
        model="ballot.Nominee",
        treatment=ARCHIVE,
        purpose="Official nominee profile and awards history.",
        automatic_days=None,
        anchor="existing nominee archive process",
        notes=(
            "Continue using the existing nominee archive/deleted_at "
            "architecture. Public-content removal remains separate from "
            "ordinary account deletion."
        ),
    ),

    RetentionRule(
        model="ballot.AtlsHottestEvent",
        treatment=ANONYMIZE,
        purpose="Event history and event administration.",
        automatic_days=730,
        anchor="event completion",
        notes=(
            "Event organizer personal contact information may be anonymized "
            "24 months after the event. Appropriate event-history information "
            "may remain archived."
        ),
    ),

    RetentionRule(
        model="ballot.AdvertisingInquiry",
        treatment=ANONYMIZE,
        purpose="Advertising sales inquiry.",
        automatic_days=365,
        anchor="last activity for stale/unconverted inquiry",
        notes=(
            "Stale, unconverted inquiry personal contact information may be "
            "anonymized after 12 months. Unneeded uploaded creative may also "
            "be removed. Converted campaigns/transactions follow their own "
            "business and financial retention rules."
        ),
    ),

    RetentionRule(
        model="ballot.AdvertisingCampaign",
        treatment=ARCHIVE,
        purpose="Advertising campaign/business history.",
        automatic_days=None,
        anchor="campaign lifecycle",
        notes=(
            "Campaign history is archived. Financial or transaction-related "
            "retention is not automatically assigned by this policy."
        ),
    ),

    RetentionRule(
        model="ballot.BillboardAdEvent",
        treatment=RETAIN,
        purpose="Aggregate advertising impression/click analytics.",
        automatic_days=None,
        anchor="analytics history",
        notes=(
            "Aggregate campaign analytics may be retained. Reassess this "
            "rule if direct personal identifiers are added later."
        ),
    ),

    RetentionRule(
        model="ballot.EventPromotionOrder",
        treatment=RETAIN,
        purpose="Paid promotion and transaction history.",
        automatic_days=None,
        anchor="financial/accounting/legal requirement",
        notes=(
            "NO AUTOMATIC PERIOD ASSIGNED. Contains producer identity and "
            "Stripe transaction references. A retention period will not be "
            "hard-coded until the applicable financial/accounting/legal "
            "requirements are separately confirmed."
        ),
    ),
)


# Sub-rules whose retention clock differs from the model's primary rule.
FIELD_RETENTION_RULES = {
    "ballot.Vote.ip_address": {
        "days": 90,
        "anchor": "voting closes",
        "action": "CLEAR",
    },
    "ballot.Vote.user_agent": {
        "days": 90,
        "anchor": "voting closes",
        "action": "CLEAR",
    },
}


def get_retention_rules():
    return RETENTION_RULES


def get_field_retention_rules():
    return FIELD_RETENTION_RULES
