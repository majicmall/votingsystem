"""
009-B8 — Advertising Campaign Delivery Lifecycle

This module owns controlled lifecycle transitions that depend on
authoritative advertising delivery analytics.

Important architectural boundary:

    advertising_campaign_delivery_analytics()

remains read-only.

Analytics determines whether delivery is complete.
This module decides whether a lifecycle transition is permitted.
"""

from django.db import transaction

from ballot.advertising_analytics import (
    advertising_campaign_delivery_analytics,
)
from ballot.models import AdvertisingCampaign


@transaction.atomic
def complete_campaign_if_fully_delivered(campaign):
    """
    Move an eligible campaign to COMPLETED only when authoritative
    delivery analytics confirms that all purchased appearances have
    verified Proof-of-Play.

    Returns True only when this call performs the lifecycle transition.

    Returns False when:
      * delivery is incomplete,
      * the campaign is already completed,
      * the campaign is cancelled,
      * or the campaign is otherwise not eligible for completion.

    This function does not manufacture delivery truth. The authoritative
    analytics service remains the source of truth.
    """

    if not isinstance(campaign, AdvertisingCampaign):
        raise TypeError(
            "campaign must be an AdvertisingCampaign instance"
        )

    # Lock the campaign row before evaluating and mutating lifecycle state.
    locked_campaign = (
        AdvertisingCampaign.objects
        .select_for_update()
        .get(pk=campaign.pk)
    )

    # Terminal states must never be rewritten.
    if locked_campaign.status == AdvertisingCampaign.STATUS_COMPLETED:
        return False

    if locked_campaign.status == AdvertisingCampaign.STATUS_CANCELLED:
        return False

    # Completion is an operational transition from a campaign that has
    # actually been delivering. Draft/pending campaigns must not jump
    # directly to completed merely because of malformed or unexpected data.
    eligible_statuses = {
        AdvertisingCampaign.STATUS_ACTIVE,
        AdvertisingCampaign.STATUS_PAUSED,
    }

    if locked_campaign.status not in eligible_statuses:
        return False

    analytics = advertising_campaign_delivery_analytics(
        locked_campaign
    )

    if not analytics["is_fully_delivered"]:
        return False

    locked_campaign.status = AdvertisingCampaign.STATUS_COMPLETED
    locked_campaign.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # Keep the caller's in-memory object synchronized with the database.
    campaign.status = locked_campaign.status

    return True
