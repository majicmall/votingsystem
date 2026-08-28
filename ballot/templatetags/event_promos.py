from django import template

from ballot.models import AtlsHottestEvent

register = template.Library()


@register.simple_tag
def homepage_featured_event():
    return (
        AtlsHottestEvent.objects
        .filter(status="approved", show_on_homepage=True, flyer__isnull=False)
        .exclude(flyer="")
        .order_by("-is_featured", "-show_today", "-updated_at")
        .first()
    )
