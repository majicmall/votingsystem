from django.contrib import messages
from django.core import signing
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from ballot.models import CommunicationPreference


User = get_user_model()


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def account_settings(request):
    """
    Central account-management screen.

    Optional promotional communications are controlled independently from
    transactional/service messages required to operate the account.
    """
    email = (request.user.email or "").strip().lower()

    preference = None
    if email:
        # Prefer the preference already owned by this account. This safely
        # handles an account email change without creating a second row for
        # the same user.
        preference = CommunicationPreference.objects.filter(
            user=request.user
        ).first()

        if preference:
            if preference.email != email:
                email_conflict = CommunicationPreference.objects.filter(
                    email=email
                ).exclude(pk=preference.pk).exists()

                if email_conflict:
                    messages.error(
                        request,
                        "Communication preferences could not be linked to this email address.",
                    )
                    preference = None
                else:
                    preference.email = email
                    preference.save(update_fields=["email", "updated_at"])
        else:
            email_preference = CommunicationPreference.objects.filter(
                email=email
            ).first()

            if email_preference:
                if email_preference.user_id is None:
                    email_preference.user = request.user
                    email_preference.save(update_fields=["user", "updated_at"])
                    preference = email_preference
                elif email_preference.user_id == request.user.id:
                    preference = email_preference
                else:
                    messages.error(
                        request,
                        "Communication preferences could not be linked to this email address.",
                    )
            else:
                preference = CommunicationPreference.objects.create(
                    email=email,
                    user=request.user,
                    marketing_allowed=False,
                )

    if request.method == "POST":
        if not preference:
            messages.error(
                request,
                "Add an email address to your account before changing communication preferences.",
            )
            return redirect("account_settings")

        action = request.POST.get("communications_action", "").strip()

        if action == "enable":
            preference.grant_marketing_consent()
            messages.success(
                request,
                "Promotional communications have been enabled.",
            )
        elif action == "disable":
            preference.withdraw_marketing_consent()
            messages.success(
                request,
                "Promotional communications have been disabled.",
            )
        else:
            messages.error(
                request,
                "We could not update that communications preference.",
            )

        return redirect("account_settings")

    return render(
        request,
        "ballot/account_settings.html",
        {
            "account_user": request.user,
            "communication_preference": preference,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def delete_account(request):
    """
    Authenticated account-deletion confirmation flow.

    A destructive deletion is never performed on GET.
    The user must confirm the account password before deletion.
    """
    if request.method == "GET":
        return render(request, "ballot/delete_account.html")

    password = request.POST.get("password", "")
    confirmation = request.POST.get("confirmation", "").strip()

    if confirmation != "DELETE":
        messages.error(
            request,
            'Type DELETE exactly to confirm account deletion.',
        )
        return render(request, "ballot/delete_account.html")

    if not request.user.check_password(password):
        messages.error(
            request,
            "Your password was not correct. Your account was not deleted.",
        )
        return render(request, "ballot/delete_account.html")

    user = request.user

    with transaction.atomic():
        # Remove account-owned uploaded profile media before deleting
        # the database record. Django CASCADE removes related rows but
        # does not automatically remove uploaded files from storage.
        try:
            association_profile = user.association_profile
        except Exception:
            association_profile = None

        if association_profile and association_profile.profile_pic:
            association_profile.profile_pic.delete(save=False)

        # Related ATL's Hottest user-owned records use CASCADE:
        # AssociationProfile, AssociationMembership,
        # NominationCategoryRequest, UserMembership, and the ATL-side
        # MajicMall Megaverse connection.
        #
        # This does NOT delete a separate MajicMall Megaverse identity.
        # Historical voting, nomination, event, advertising, and payment
        # records are governed separately by ATL's Hottest retention rules.
        user.delete()

    logout(request)

    return redirect("account_deleted")


@require_http_methods(["GET"])
def account_deleted(request):
    return render(request, "ballot/account_deleted.html")


@require_http_methods(["GET"])
def account_deletion_info(request):
    """
    Public account-deletion information page.

    This route is intentionally accessible without authentication so it
    can be supplied to app-store account-deletion disclosures.
    """
    return render(request, "ballot/account_deletion_info.html")


@require_http_methods(["GET"])
def privacy_policy(request):
    return render(request, "ballot/privacy_policy.html")


@require_http_methods(["GET"])
def terms_of_service(request):
    return render(request, "ballot/terms_of_service.html")


@require_http_methods(["GET", "POST"])
@csrf_protect
def communications_unsubscribe(request, token):
    """
    Public confirmation endpoint for withdrawing optional promotional
    communications.

    GET never changes the preference. POST performs the withdrawal.
    """
    from ballot.email_utils import communications_email_from_token

    try:
        email = communications_email_from_token(token)
    except signing.BadSignature:
        return render(
            request,
            "ballot/communications_unsubscribe.html",
            {"invalid_token": True},
            status=400,
        )

    preference = CommunicationPreference.objects.filter(email=email).first()

    if request.method == "POST":
        if preference and preference.marketing_allowed:
            preference.withdraw_marketing_consent()

        return render(
            request,
            "ballot/communications_unsubscribe.html",
            {
                "unsubscribed": True,
                "email": email,
            },
        )

    return render(
        request,
        "ballot/communications_unsubscribe.html",
        {
            "email": email,
            "already_unsubscribed": bool(
                preference and not preference.marketing_allowed
            ),
        },
    )
