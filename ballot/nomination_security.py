"""
ATL's Hottest nomination security protections.

Additive security module. Existing nomination features remain unchanged.
"""

import logging

logger = logging.getLogger(__name__)

HONEYPOT_FIELD = "nomination_reference_code"


def nomination_honeypot_triggered(request):
    """
    Detect submissions that fill the hidden anti-bot field.

    Returns True when the request should be rejected.
    """
    if request.method != "POST":
        return False

    value = request.POST.get(HONEYPOT_FIELD, "")

    if value and value.strip():
        logger.warning(
            "Nomination honeypot triggered."
        )
        return True

    return False


def nomination_turnstile_enabled():
    """Turnstile is active only when explicitly configured."""
    from django.conf import settings

    return bool(
        getattr(settings, "NOMINATION_TURNSTILE_ENABLED", False)
        and getattr(settings, "NOMINATION_TURNSTILE_SITE_KEY", "")
        and getattr(settings, "NOMINATION_TURNSTILE_SECRET_KEY", "")
    )


def verify_nomination_turnstile(request):
    """
    Verify a nomination's Turnstile token with Cloudflare.

    Returns True when Turnstile is disabled or verification succeeds.
    """
    if not nomination_turnstile_enabled():
        return True

    import requests
    from django.conf import settings

    token = request.POST.get("cf-turnstile-response", "").strip()
    if not token:
        return False

    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": settings.NOMINATION_TURNSTILE_SECRET_KEY,
                "response": token,
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json().get("success") is True
    except (requests.RequestException, ValueError):
        logger.warning("Nomination Turnstile verification failed.")
        return False
