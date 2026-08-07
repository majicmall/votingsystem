from django import template
from django.utils import timezone

from ballot.models import BillboardAd

register = template.Library()


@register.inclusion_tag("ballot/partials/billboard_ad.html")
def render_billboard(placement):
    now = timezone.now()
    ad = (
        BillboardAd.objects
        .filter(is_active=True, placement=placement)
        .filter(
            models_q_starts(now),
            models_q_ends(now),
        )
        .order_by("priority", "-created_at")
        .first()
    )
    return {"ad": ad, "placement": placement}


def models_q_starts(now):
    from django.db.models import Q
    return Q(starts_at__isnull=True) | Q(starts_at__lte=now)


def models_q_ends(now):
    from django.db.models import Q
    return Q(ends_at__isnull=True) | Q(ends_at__gte=now)
