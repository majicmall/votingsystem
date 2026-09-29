from django import template
from django.db.models import Q
from django.utils import timezone

from ballot.models import (
    AdvertisingPlayoutReservation,
    BillboardAd,
    BillboardAdEvent,
)


register = template.Library()


# Each rotation window lasts this many seconds.
# Visitors loading during the same window see a stable selection,
# while the property rotates automatically over time.
ROTATION_WINDOW_SECONDS = 15


@register.inclusion_tag("ballot/partials/billboard_ad.html")
def render_billboard(placement):
    now = timezone.now()

    eligible_ads = (
        BillboardAd.objects
        .filter(
            is_active=True,
            placement=placement,
        )
        .filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now),
            Q(ends_at__isnull=True) | Q(ends_at__gte=now),
        )
    )

    # =====================================================
    # EXCLUSIVE WHOLE-BILLBOARD TAKEOVER
    # =====================================================
    # Any currently active exclusive purchase owns the
    # property. Priority resolves accidental overlaps.
    exclusive_ad = (
        eligible_ads
        .filter(purchase_type=BillboardAd.PURCHASE_EXCLUSIVE)
        .order_by("priority", "-created_at")
        .first()
    )

    if exclusive_ad:
        BillboardAdEvent.objects.create(
            ad=exclusive_ad,
            event_type=BillboardAdEvent.EVENT_IMPRESSION,
            placement=placement,
        )

        return {
            "ad": exclusive_ad,
            "placement": placement,
            "billboard_mode": "exclusive",
        }

    # =====================================================
    # 009-A2C — AMBE SCHEDULED LIVE DELIVERY
    # =====================================================
    #
    # A reservation owns one exact six-second inventory unit.
    # Longer appearances therefore remain selected across each
    # consecutive reservation row sharing the same appearance_id.
    #
    # IMPORTANT:
    # Selection is NOT Proof of Play. The reservation remains
    # RESERVED here. A later player acknowledgement will call
    # the authoritative Proof-of-Play recorder only after the
    # required presentation has actually completed.
    #
    ambe_reservation = (
        AdvertisingPlayoutReservation.objects
        .select_related(
            "creative",
            "creative__billboard_ad",
        )
        .filter(
            placement=placement,
            status=AdvertisingPlayoutReservation.STATUS_RESERVED,
            slot_start__lte=now,
            slot_end__gt=now,
            creative__is_active=True,
            creative__billboard_ad__isnull=False,
            creative__billboard_ad__is_active=True,
        )
        .order_by(
            "slot_start",
            "sequence_number",
            "pk",
        )
        .first()
    )

    if ambe_reservation:
        ambe_ad = ambe_reservation.creative.billboard_ad

        BillboardAdEvent.objects.create(
            ad=ambe_ad,
            event_type=BillboardAdEvent.EVENT_IMPRESSION,
            placement=placement,
        )

        return {
            "ad": ambe_ad,
            "placement": placement,
            "billboard_mode": "ambe",
            "ambe_reservation": ambe_reservation,
            "ambe_appearance_id": ambe_reservation.appearance_id,
            "ambe_sequence_number": ambe_reservation.sequence_number,
            "ambe_appearance_slot_count": (
                ambe_reservation.appearance_slot_count
            ),
        }

    # =====================================================
    # WEIGHTED ROTATING INVENTORY
    # =====================================================
    # AMBE-managed BillboardAds may only appear through a live
    # AdvertisingPlayoutReservation. If AMBE has no reservation for
    # the current slot, those ads must not leak into legacy rotation.
    #
    # billboard_ad is the presentation bridge installed in 009-A2B.
    rotating_ads = list(
        eligible_ads
        .filter(purchase_type=BillboardAd.PURCHASE_ROTATION)
        .filter(playout_creatives__isnull=True)
        .order_by("priority", "created_at", "pk")
        .distinct()
    )

    if not rotating_ads:
        return {
            "ad": None,
            "placement": placement,
            "billboard_mode": "house",
        }

    weighted_ads = []

    for ad in rotating_ads:
        weight = max(1, int(ad.rotation_weight or 1))
        weighted_ads.extend([ad] * weight)

    # Stable time-based rotation.
    # Including the placement in the index prevents every
    # billboard property from rotating in perfect lockstep.
    window_number = int(now.timestamp()) // ROTATION_WINDOW_SECONDS
    placement_offset = sum(ord(char) for char in placement)

    selected_index = (
        window_number + placement_offset
    ) % len(weighted_ads)

    selected_ad = weighted_ads[selected_index]

    BillboardAdEvent.objects.create(
        ad=selected_ad,
        event_type=BillboardAdEvent.EVENT_IMPRESSION,
        placement=placement,
    )

    return {
        "ad": selected_ad,
        "placement": placement,
        "billboard_mode": "rotation",
    }
