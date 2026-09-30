from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Max, Min, Sum

from ballot.models import (
    AdvertisingCampaign,
    AdvertisingCampaignSpend,
    AdvertisingPlayoutReservation,
)


ZERO_MONEY = Decimal("0.00")


def _money(value):
    return value if value is not None else ZERO_MONEY


def advertising_campaign_delivery_analytics(campaign):
    """
    Return authoritative delivery analytics for one advertising campaign.

    Accounting rules:

    * AdvertisingCampaignSpend is authoritative for purchased media spend.
    * appearance_id is the unit of an advertising appearance.
    * AdvertisingPlayoutReservation rows are six-second inventory slots.
    * Multiple reservation rows may belong to one appearance.
    * An appearance counts as played only when every reservation row for
      that appearance is STATUS_PLAYED.
    * An appearance counts as reserved only when every reservation row for
      that appearance is STATUS_RESERVED.
    * Mixed/incomplete states are not fabricated into successful delivery.
    """

    if not isinstance(campaign, AdvertisingCampaign):
        raise ValidationError(
            "campaign must be an AdvertisingCampaign instance."
        )

    spends = list(
        AdvertisingCampaignSpend.objects
        .filter(campaign=campaign)
        .order_by("created_at", "pk")
    )

    reservations = list(
        AdvertisingPlayoutReservation.objects
        .filter(campaign=campaign)
        .order_by(
            "appearance_id",
            "sequence_number",
            "slot_start",
            "pk",
        )
    )

    # ---------------------------------------------------------
    # PURCHASE / MONEY LEDGER
    # ---------------------------------------------------------
    purchased_appearance_ids = {
        spend.appearance_id
        for spend in spends
    }

    purchased_appearances = len(purchased_appearance_ids)

    purchased_slots = sum(
        int(spend.slot_count or 0)
        for spend in spends
    )

    media_spend = _money(
        AdvertisingCampaignSpend.objects
        .filter(campaign=campaign)
        .aggregate(total=Sum("media_spend"))
        ["total"]
    )

    platform_share = _money(
        AdvertisingCampaignSpend.objects
        .filter(campaign=campaign)
        .aggregate(total=Sum("platform_share_amount"))
        ["total"]
    )

    # ---------------------------------------------------------
    # RESERVATION / PROOF-OF-PLAY LEDGER
    # ---------------------------------------------------------
    by_appearance = defaultdict(list)

    for reservation in reservations:
        by_appearance[reservation.appearance_id].append(
            reservation
        )

    reserved_appearances = 0
    played_appearances = 0
    cancelled_appearances = 0
    missed_appearances = 0
    mixed_appearances = 0

    reserved_slots = 0
    played_slots = 0
    cancelled_slots = 0
    missed_slots = 0

    placement_data = defaultdict(
        lambda: {
            "purchased_appearances": 0,
            "reserved_appearances": 0,
            "played_appearances": 0,
            "slot_count": 0,
            "media_spend": ZERO_MONEY,
        }
    )

    creative_data = defaultdict(
        lambda: {
            "creative_id": None,
            "creative_name": "",
            "purchased_appearances": 0,
            "reserved_appearances": 0,
            "played_appearances": 0,
            "slot_count": 0,
            "media_spend": ZERO_MONEY,
        }
    )

    # Purchased analytics come from the immutable spend ledger.
    for spend in spends:
        placement = spend.placement

        placement_data[placement][
            "purchased_appearances"
        ] += 1

        placement_data[placement]["slot_count"] += int(
            spend.slot_count or 0
        )

        placement_data[placement]["media_spend"] += _money(
            spend.media_spend
        )

        creative_id = spend.creative_id
        creative_bucket = creative_data[creative_id]

        creative_bucket["creative_id"] = creative_id
        creative_bucket["creative_name"] = (
            str(spend.creative)
            if spend.creative_id
            else ""
        )
        creative_bucket["purchased_appearances"] += 1
        creative_bucket["slot_count"] += int(
            spend.slot_count or 0
        )
        creative_bucket["media_spend"] += _money(
            spend.media_spend
        )

    for appearance_id, rows in by_appearance.items():
        statuses = {row.status for row in rows}

        reserved_slots += sum(
            1
            for row in rows
            if row.status
            == AdvertisingPlayoutReservation.STATUS_RESERVED
        )

        played_slots += sum(
            1
            for row in rows
            if row.status
            == AdvertisingPlayoutReservation.STATUS_PLAYED
        )

        cancelled_slots += sum(
            1
            for row in rows
            if row.status
            == AdvertisingPlayoutReservation.STATUS_CANCELLED
        )

        missed_slots += sum(
            1
            for row in rows
            if row.status
            == AdvertisingPlayoutReservation.STATUS_MISSED
        )

        placement = rows[0].placement
        creative_id = rows[0].creative_id

        if statuses == {
            AdvertisingPlayoutReservation.STATUS_RESERVED
        }:
            reserved_appearances += 1
            placement_data[placement][
                "reserved_appearances"
            ] += 1

            creative_data[creative_id][
                "creative_id"
            ] = creative_id

            creative_data[creative_id][
                "creative_name"
            ] = str(rows[0].creative)

            creative_data[creative_id][
                "reserved_appearances"
            ] += 1

        elif statuses == {
            AdvertisingPlayoutReservation.STATUS_PLAYED
        }:
            played_appearances += 1
            placement_data[placement][
                "played_appearances"
            ] += 1

            creative_data[creative_id][
                "creative_id"
            ] = creative_id

            creative_data[creative_id][
                "creative_name"
            ] = str(rows[0].creative)

            creative_data[creative_id][
                "played_appearances"
            ] += 1

        elif statuses == {
            AdvertisingPlayoutReservation.STATUS_CANCELLED
        }:
            cancelled_appearances += 1

        elif statuses == {
            AdvertisingPlayoutReservation.STATUS_MISSED
        }:
            missed_appearances += 1

        else:
            mixed_appearances += 1

    # ---------------------------------------------------------
    # AUTHORITATIVE DELIVERY VALUE
    # ---------------------------------------------------------
    played_appearance_ids = {
        appearance_id
        for appearance_id, rows in by_appearance.items()
        if {
            row.status
            for row in rows
        } == {
            AdvertisingPlayoutReservation.STATUS_PLAYED
        }
    }

    delivered_media_spend = sum(
        (
            _money(spend.media_spend)
            for spend in spends
            if spend.appearance_id in played_appearance_ids
        ),
        ZERO_MONEY,
    )

    outstanding_media_spend = (
        media_spend - delivered_media_spend
    )

    if outstanding_media_spend < ZERO_MONEY:
        outstanding_media_spend = ZERO_MONEY

    outstanding_appearances = max(
        purchased_appearances - played_appearances,
        0,
    )

    is_fully_delivered = (
        purchased_appearances > 0
        and played_appearances == purchased_appearances
        and outstanding_appearances == 0
    )

    if purchased_appearances:
        delivery_percentage = (
            Decimal(played_appearances)
            / Decimal(purchased_appearances)
            * Decimal("100")
        ).quantize(Decimal("0.01"))
    else:
        delivery_percentage = Decimal("0.00")

    play_window = (
        AdvertisingPlayoutReservation.objects
        .filter(
            campaign=campaign,
            status=AdvertisingPlayoutReservation.STATUS_PLAYED,
        )
        .aggregate(
            first_played_at=Min("played_at"),
            last_played_at=Max("played_at"),
        )
    )

    placement_breakdown = []

    for placement in sorted(placement_data):
        row = placement_data[placement]
        placement_breakdown.append({
            "placement": placement,
            **row,
        })

    creative_breakdown = []

    for creative_id in sorted(
        creative_data,
        key=lambda value: (
            value is None,
            value or 0,
        ),
    ):
        creative_breakdown.append(
            creative_data[creative_id]
        )

    return {
        "campaign": campaign,

        # Purchase contract.
        "purchased_appearances": purchased_appearances,
        "purchased_slots": purchased_slots,
        "media_spend": media_spend,
        "platform_share_amount": platform_share,

        # Reservation / delivery contract.
        "reserved_appearances": reserved_appearances,
        "played_appearances": played_appearances,
        "cancelled_appearances": cancelled_appearances,
        "missed_appearances": missed_appearances,
        "mixed_appearances": mixed_appearances,

        "reserved_slots": reserved_slots,
        "played_slots": played_slots,
        "cancelled_slots": cancelled_slots,
        "missed_slots": missed_slots,

        # Delivery performance.
        "outstanding_appearances": outstanding_appearances,
        "delivery_percentage": delivery_percentage,
        "is_fully_delivered": is_fully_delivered,
        "delivered_media_spend": delivered_media_spend,
        "outstanding_media_spend": outstanding_media_spend,

        # Proof-of-Play window.
        "first_played_at": play_window["first_played_at"],
        "last_played_at": play_window["last_played_at"],

        # Drill-downs.
        "placement_breakdown": placement_breakdown,
        "creative_breakdown": creative_breakdown,
    }
