from __future__ import annotations

import secrets
import time
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .models import MegaverseConnection
from .services import MegaverseClient, MegaverseError


SESSION_STATE_KEY = "megaverse_link_state"
SESSION_RESULT_KEY = "megaverse_link_result"

AUTHORIZATION_PATH = "/connect/atls-hottest/"
EXCHANGE_PATH = "/api/megaverse/identity/exchange/"

STATE_LIFETIME_SECONDS = 600


def _set_result(request, *, success: bool, title: str, message: str) -> None:
    request.session[SESSION_RESULT_KEY] = {
        "success": success,
        "title": title,
        "message": message,
    }


def _redirect_to_result(request):
    return redirect("megaverse:link_result")


@login_required
@never_cache
def start_link(request):
    """
    Begin the ATL's Hottest -> MajicMall Megaverse identity connection.

    A cryptographically-random state value is stored in the ATL's Hottest
    session before the browser leaves this site.
    """

    base_url = settings.MEGAVERSE_API_BASE_URL.rstrip("/")
    api_key = settings.MEGAVERSE_API_KEY

    if not base_url or not api_key:
        _set_result(
            request,
            success=False,
            title="Connection unavailable",
            message=(
                "The MajicMall Megaverse connection is not configured yet. "
                "Please try again later."
            ),
        )
        return _redirect_to_result(request)

    state = secrets.token_urlsafe(32)

    request.session[SESSION_STATE_KEY] = {
        "value": state,
        "issued_at": int(time.time()),
    }

    query = urlencode({"state": state})
    authorization_url = f"{base_url}{AUTHORIZATION_PATH}?{query}"

    return redirect(authorization_url)


@login_required
@never_cache
def link_callback(request):
    """
    Receive the short-lived authorization code from MajicMall Megaverse.

    The state value is consumed before any exchange occurs. The authorization
    code is then exchanged server-to-server using ATL's Hottest's bridge key.
    """

    expected_state_data = request.session.pop(SESSION_STATE_KEY, None)

    returned_state = (request.GET.get("state") or "").strip()
    returned_error = (request.GET.get("error") or "").strip()
    code = (request.GET.get("code") or "").strip()

    if not isinstance(expected_state_data, dict):
        _set_result(
            request,
            success=False,
            title="Connection could not be verified",
            message="The connection request is missing or has already been used.",
        )
        return _redirect_to_result(request)

    expected_state = str(expected_state_data.get("value") or "")
    issued_at = expected_state_data.get("issued_at")

    if not expected_state or not returned_state:
        _set_result(
            request,
            success=False,
            title="Connection could not be verified",
            message="The security state value is missing.",
        )
        return _redirect_to_result(request)

    if not secrets.compare_digest(expected_state, returned_state):
        _set_result(
            request,
            success=False,
            title="Connection could not be verified",
            message="The security state value did not match.",
        )
        return _redirect_to_result(request)

    try:
        state_age = int(time.time()) - int(issued_at)
    except (TypeError, ValueError):
        state_age = STATE_LIFETIME_SECONDS + 1

    if state_age < 0 or state_age > STATE_LIFETIME_SECONDS:
        _set_result(
            request,
            success=False,
            title="Connection expired",
            message="The connection request expired. Please start again.",
        )
        return _redirect_to_result(request)

    if returned_error:
        _set_result(
            request,
            success=False,
            title="Connection cancelled",
            message="Your MajicMall Megaverse account was not connected.",
        )
        return _redirect_to_result(request)

    if not code:
        _set_result(
            request,
            success=False,
            title="Connection could not be completed",
            message="MajicMall Megaverse did not return an authorization code.",
        )
        return _redirect_to_result(request)

    try:
        response = MegaverseClient().post(
            EXCHANGE_PATH,
            payload={"code": code},
        )
    except MegaverseError:
        _set_result(
            request,
            success=False,
            title="Connection temporarily unavailable",
            message=(
                "ATL's Hottest could not complete the secure MajicMall "
                "Megaverse exchange. Please try again."
            ),
        )
        return _redirect_to_result(request)

    data = response.data

    if not isinstance(data, dict) or not data.get("ok"):
        _set_result(
            request,
            success=False,
            title="Connection could not be completed",
            message="MajicMall Megaverse returned an invalid connection response.",
        )
        return _redirect_to_result(request)

    raw_ref = str(data.get("megaverse_user_ref") or "").strip()

    try:
        megaverse_user_ref = str(uuid.UUID(raw_ref))
    except (ValueError, AttributeError):
        _set_result(
            request,
            success=False,
            title="Connection could not be completed",
            message="MajicMall Megaverse returned an invalid identity reference.",
        )
        return _redirect_to_result(request)

    now = timezone.now()

    try:
        with transaction.atomic():
            connection, _ = MegaverseConnection.objects.select_for_update().get_or_create(
                user=request.user
            )

            if (
                connection.megaverse_user_ref
                and connection.megaverse_user_ref != megaverse_user_ref
            ):
                _set_result(
                    request,
                    success=False,
                    title="Account already connected",
                    message=(
                        "This ATL's Hottest account is already connected to a "
                        "different MajicMall Megaverse identity."
                    ),
                )
                return _redirect_to_result(request)

            already_claimed = (
                MegaverseConnection.objects
                .exclude(pk=connection.pk)
                .filter(megaverse_user_ref=megaverse_user_ref)
                .exists()
            )

            if already_claimed:
                _set_result(
                    request,
                    success=False,
                    title="Identity already connected",
                    message=(
                        "That MajicMall Megaverse identity is already connected "
                        "to another ATL's Hottest account."
                    ),
                )
                return _redirect_to_result(request)

            connection.megaverse_user_ref = megaverse_user_ref
            connection.is_linked = True

            if connection.linked_at is None:
                connection.linked_at = now

            connection.last_synced_at = now

            connection.save(
                update_fields=[
                    "megaverse_user_ref",
                    "is_linked",
                    "linked_at",
                    "last_synced_at",
                    "updated_at",
                ]
            )

    except IntegrityError:
        _set_result(
            request,
            success=False,
            title="Identity already connected",
            message=(
                "That MajicMall Megaverse identity is already connected "
                "to another ATL's Hottest account."
            ),
        )
        return _redirect_to_result(request)

    _set_result(
        request,
        success=True,
        title="MajicMall Megaverse connected",
        message=(
            "Your ATL's Hottest account is now securely connected to your "
            "MajicMall Megaverse identity."
        ),
    )

    return _redirect_to_result(request)


@login_required
@never_cache
def link_result(request):
    result = request.session.pop(
        SESSION_RESULT_KEY,
        {
            "success": False,
            "title": "No connection result",
            "message": "Start a MajicMall Megaverse connection to continue.",
        },
    )

    response = render(
        request,
        "megaverse/link_result.html",
        {
            "success": bool(result.get("success")),
            "title": result.get("title"),
            "message": result.get("message"),
        },
    )

    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"

    return response
