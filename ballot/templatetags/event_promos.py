from django import template
from django.utils import timezone

from ballot.models import AtlsHottestEvent


register = template.Library()


@register.simple_tag
def homepage_featured_event():
    """
    Return one event eligible for premium homepage placement.

    Paid homepage placement requires:

    - approved event
    - homepage master switch ON
    - Paid or Complimentary payment status
    - promotion start reached
    - promotion end not yet reached
    - flyer available

    When more than one paid promotion is active, the eligible
    events rotate by minute so multiple producers may share the
    premium homepage inventory.

    During migration to the paid system, legacy homepage events
    using the old checkbox remain supported only when they have
    not yet been assigned a promotion/payment package.
    """

    now = timezone.now()

    active_promotions = (
        AtlsHottestEvent.objects
        .filter(
            status="approved",
            show_on_homepage=True,
            homepage_payment_status__in=["paid", "comp"],
            homepage_promotion_start__lte=now,
            homepage_promotion_end__gt=now,
            flyer__isnull=False,
        )
        .exclude(flyer="")
        .order_by(
            "homepage_promotion_start",
            "pk",
        )
    )

    active_count = active_promotions.count()

    if active_count:
        rotation_index = int(now.timestamp() // 60) % active_count
        return active_promotions[rotation_index]

    # --------------------------------------------------------
    # TEMPORARY LEGACY FALLBACK
    #
    # This protects the currently working homepage event while
    # existing events are migrated into the new paid system.
    #
    # Once all homepage placements use paid/comp campaigns,
    # this fallback can be removed.
    # --------------------------------------------------------

    return (
        AtlsHottestEvent.objects
        .filter(
            status="approved",
            show_on_homepage=True,
            homepage_payment_status="not_required",
            homepage_package="",
            flyer__isnull=False,
        )
        .exclude(flyer="")
        .order_by(
            "-is_featured",
            "-show_today",
            "-updated_at",
        )
        .first()
    )
