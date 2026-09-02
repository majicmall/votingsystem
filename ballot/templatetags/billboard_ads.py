from django import template
from django.db.models import Q
from django.utils import timezone

from ballot.models import BillboardAd, BillboardAdEvent


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
    # WEIGHTED ROTATING INVENTORY
    # =====================================================
    rotating_ads = list(
        eligible_ads
        .filter(purchase_type=BillboardAd.PURCHASE_ROTATION)
        .order_by("priority", "created_at", "pk")
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
