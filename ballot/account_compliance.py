from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods


User = get_user_model()


@login_required
@require_http_methods(["GET"])
def account_settings(request):
    """
    Central account-management screen.

    This becomes the in-app location for security, privacy,
    and account-deletion controls.
    """
    return render(
        request,
        "ballot/account_settings.html",
        {
            "account_user": request.user,
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
        # IMPORTANT:
        # Related ATL's Hottest user-owned records currently use CASCADE.
        # This removes the ATL-side MajicMall Megaverse connection only;
        # it does not delete the external MajicMall Megaverse identity.
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
