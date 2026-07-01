# ballot/views.py
from __future__ import annotations

import csv
import json
import uuid

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .forms import CategoryRequestForm, NomineePhotoForm, NomineeProfileForm, NomineeSignupForm
from .models import (
    AssociationMembership,
    BallotSettings,
    Category,
    NominationCategoryRequest,
    Nominee,
    Vote,
)
from .services import approve_category_request, deny_category_request


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _user_can_manage_nominee(user, nominee):
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    return AssociationMembership.objects.filter(
        user=user,
        nominee=nominee,
        is_active=True,
    ).exists()


@require_http_methods(["GET"])
def ballot_view(request):
    ballot_settings = BallotSettings.get_solo()

    categories_display = []
    for category in Category.objects.for_ballot():
        nominees = getattr(category, "prefetched_nominees", [])
        categories_display.append(
            {
                "category": category,
                "nominees": nominees,
            }
        )

    return render(
        request,
        "ballot/ballot.html",
        {
            "settings": ballot_settings,
            "categories_display": categories_display,
        },
    )


@require_POST
@csrf_protect
def submit_votes(request):
    ballot_settings = BallotSettings.get_solo()

    if not ballot_settings.is_active():
        status = ballot_settings.status_label()
        message = "Voting is not available right now."
        if status == "paused":
            message = "Voting is temporarily paused."
        elif status == "scheduled":
            message = "Voting has not started yet."
        elif status in ("ended", "stopped"):
            message = "Voting has ended."
        return JsonResponse({"message": message, "status": status}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid vote data."}, status=400)

    email = (payload.get("email") or "").strip().lower()
    selections = payload.get("selections") or {}

    if not email:
        return JsonResponse({"message": "Email is required."}, status=400)

    if not isinstance(selections, dict) or not selections:
        return JsonResponse({"message": "Please select at least one nominee."}, status=400)

    saved = []
    skipped = []
    errors = []

    for category_slug, nominee_id in selections.items():
        try:
            category = Category.objects.get(slug=category_slug, is_active=True)
            nominee = Nominee.objects.get(id=nominee_id, category=category, is_active=True)
        except (Category.DoesNotExist, Nominee.DoesNotExist):
            errors.append({"category": category_slug, "message": "Invalid nominee selection."})
            continue

        try:
            Vote.objects.create(
                email=email,
                category=category,
                nominee=nominee,
                ip_address=_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
            saved.append({"category": category.name, "nominee": nominee.name})
        except IntegrityError:
            skipped.append({"category": category.name, "message": "Already voted in this category."})

    return JsonResponse(
        {
            "message": "Your votes have been recorded.",
            "saved": saved,
            "skipped": skipped,
            "errors": errors,
        }
    )


@require_http_methods(["GET", "POST"])
@csrf_protect
def signup(request):
    if request.user.is_authenticated:
        return redirect("assoc_dashboard")

    form = UserCreationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Account created. Please log in.")
        return redirect("login")

    return render(request, "ballot/signup.html", {"form": form})


@require_http_methods(["GET", "POST"])
@csrf_protect
def nominee_upload(request, token):
    nominee = get_object_or_404(Nominee, upload_token=token, is_active=True)
    form = NomineePhotoForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        nominee.photo = form.cleaned_data["photo"]
        nominee.photo_submitted_at = timezone.now()
        nominee.save(update_fields=["photo", "photo_submitted_at", "updated_at"])
        return render(request, "ballot/nominee_upload_success.html", {"nominee": nominee})

    return render(request, "ballot/nominee_upload.html", {"nominee": nominee, "form": form})


@require_http_methods(["GET", "POST"])
@csrf_protect
def association_join(request):
    if not request.user.is_authenticated:
        return render(request, "ballot/association_join.html")

    if request.method == "POST":
        nominee_id = (request.POST.get("nominee_id") or "").strip()
        nominee = get_object_or_404(Nominee, id=nominee_id, is_active=True)

        membership, created = AssociationMembership.objects.get_or_create(
            user=request.user,
            nominee=nominee,
            defaults={"is_active": False},
        )

        if membership.is_active:
            messages.success(request, "You already have access to manage this nominee.")
        elif created:
            messages.success(request, "Request submitted. Staff can approve it in admin.")
        else:
            messages.info(request, "Your request is already pending.")

        return redirect("assoc_dashboard")

    nominees = Nominee.objects.active().select_related("category").order_by("name")
    return render(request, "ballot/association_join.html", {"nominees": nominees})


@login_required
@require_http_methods(["GET"])
def association_dashboard(request):
    memberships = (
        AssociationMembership.objects.filter(user=request.user)
        .select_related("nominee", "nominee__category")
        .order_by("nominee__name")
    )

    active_memberships = [m for m in memberships if m.is_active]
    pending_memberships = [m for m in memberships if not m.is_active]

    return render(
        request,
        "ballot/association_dashboard.html",
        {
            "active_memberships": active_memberships,
            "pending_memberships": pending_memberships,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def association_nominee_edit(request, nominee_id):
    nominee = get_object_or_404(Nominee, id=nominee_id)

    if not _user_can_manage_nominee(request.user, nominee):
        messages.error(request, "You do not have permission to edit this nominee.")
        return redirect("assoc_dashboard")

    form = NomineeProfileForm(request.POST or None, request.FILES or None, instance=nominee)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Nominee profile updated.")
        return redirect("assoc_dashboard")

    return render(request, "ballot/association_nominee_edit.html", {"nominee": nominee, "form": form})


@login_required
@require_POST
@csrf_protect
def association_nominee_regen_link(request, nominee_id):
    nominee = get_object_or_404(Nominee, id=nominee_id)

    if not _user_can_manage_nominee(request.user, nominee):
        messages.error(request, "You do not have permission to regenerate this link.")
        return redirect("assoc_dashboard")

    nominee.upload_token = uuid.uuid4()
    nominee.save(update_fields=["upload_token", "updated_at"])
    messages.success(request, "Upload link regenerated.")
    return redirect("assoc_dashboard")


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def request_categories(request, nominee_id):
    nominee = get_object_or_404(Nominee, id=nominee_id, is_active=True)

    if not _user_can_manage_nominee(request.user, nominee):
        messages.error(request, "You do not have permission to request categories for this nominee.")
        return redirect("assoc_dashboard")

    form = CategoryRequestForm(nominee, request.POST or None)

    if request.method == "POST" and form.is_valid():
        created_count = 0

        for category in form.cleaned_data["categories"]:
            _req, created = NominationCategoryRequest.objects.get_or_create(
                requester=request.user,
                source_nominee=nominee,
                target_category=category,
                defaults={"status": NominationCategoryRequest.STATUS_PENDING},
            )
            if created:
                created_count += 1

        if created_count:
            messages.success(request, f"Submitted {created_count} category request(s).")
        else:
            messages.info(request, "Those category requests already exist.")

        return redirect("assoc_dashboard")

    return render(request, "ballot/request_categories.html", {"nominee": nominee, "form": form})


@login_required
@require_POST
@csrf_protect
def association_nominee_delete(request, nominee_id):
    nominee = get_object_or_404(Nominee, id=nominee_id)

    if not _user_can_manage_nominee(request.user, nominee):
        messages.error(request, "You do not have permission to archive this nominee.")
        return redirect("assoc_dashboard")

    nominee.archive()
    messages.success(request, "Nominee archived.")
    return redirect("assoc_dashboard")


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def nominee_signup(request):
    form = NomineeSignupForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        nominee_name = form.cleaned_data["nominee_name"].strip()
        photo = form.cleaned_data.get("photo")
        created = []

        for category in form.cleaned_data["categories"]:
            nominee, _was_created = Nominee.objects.get_or_create(
                name=nominee_name,
                category=category,
                defaults={
                    "website": form.cleaned_data.get("website", ""),
                    "social_link": form.cleaned_data.get("social_link", ""),
                    "contact_email": form.cleaned_data.get("contact_email", ""),
                    "photo": photo,
                    "photo_submitted_at": timezone.now() if photo else None,
                    "approval_status": Nominee.APPROVAL_PENDING,
                    "is_active": True,
                },
            )

            AssociationMembership.objects.get_or_create(
                user=request.user,
                nominee=nominee,
                defaults={"is_active": False},
            )
            created.append(nominee)

        messages.success(
            request,
            "Nominee signup submitted. Staff can approve dashboard access in admin.",
        )
        return redirect("assoc_dashboard")

    return render(request, "ballot/nominee_signup.html", {"form": form})


@staff_member_required
@require_http_methods(["GET"])
def staff_dashboard(request):
    pending_requests = (
        NominationCategoryRequest.objects.filter(status=NominationCategoryRequest.STATUS_PENDING)
        .select_related("requester", "source_nominee", "target_category")
        .order_by("-created_at")
    )

    pending_memberships = (
        AssociationMembership.objects.filter(is_active=False)
        .select_related("user", "nominee", "nominee__category")
        .order_by("-created_at")
    )

    tallies = list(Vote.objects.tallies())

    return render(
        request,
        "ballot/staff_dashboard.html",
        {
            "pending_requests": pending_requests,
            "pending_memberships": pending_memberships,
            "tallies": tallies,
        },
    )


@staff_member_required
@require_POST
@csrf_protect
def staff_request_approve(request, req_id):
    req = get_object_or_404(NominationCategoryRequest, id=req_id)
    approve_category_request(req)
    messages.success(request, "Category request approved.")
    return redirect("staff_dashboard")


@staff_member_required
@require_POST
@csrf_protect
def staff_request_deny(request, req_id):
    req = get_object_or_404(NominationCategoryRequest, id=req_id)
    deny_category_request(req)
    messages.success(request, "Category request denied.")
    return redirect("staff_dashboard")


@staff_member_required
@require_http_methods(["GET"])
def tallies_json(request):
    data = {}

    for row in Vote.objects.tallies():
        category_slug = row["category__slug"]
        data.setdefault(
            category_slug,
            {
                "category": row["category__name"],
                "nominees": [],
            },
        )
        data[category_slug]["nominees"].append(
            {
                "nominee_id": row["nominee__id"],
                "nominee": row["nominee__name"],
                "votes": row["count"],
            }
        )

    return JsonResponse({"generated_at": timezone.now().isoformat(), "categories": data})


@staff_member_required
@require_http_methods(["GET"])
def export_votes_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="atl_hottest_vote_tallies.csv"'

    writer = csv.writer(response)
    writer.writerow(["category_slug", "category_name", "nominee_id", "nominee_name", "votes"])

    for row in Vote.objects.tallies():
        writer.writerow(
            [
                row["category__slug"],
                row["category__name"],
                row["nominee__id"],
                row["nominee__name"],
                row["count"],
            ]
        )

    return response


@require_http_methods(["GET", "POST"])
@csrf_protect
def upload_test(request):
    return render(request, "ballot/upload_test.html")


@require_http_methods(["GET", "POST"])
def logout_then_home(request):
    logout(request)
    return redirect("/")
