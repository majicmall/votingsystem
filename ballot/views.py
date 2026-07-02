# ballot/views.py
from __future__ import annotations

import csv
import json
import uuid

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError
from django.http import JsonResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .forms import AssociationProfileForm, CategoryRequestForm, NomineePhotoForm, NomineeProfileForm, NomineeSignupForm
from .models import (
    AssociationMembership,
    AssociationProfile,
    BallotSettings,
    Category,
    NominationCategoryRequest,
    Nominee,
    Vote,
)
from .services import approve_category_request, deny_category_request


CONFIRMATION_AD_MESSAGE = """
Sponsored Message:
ATL's Hottest Awards supporters help keep the culture moving. Watch for featured offers, sponsor announcements, and red-carpet updates from ATL's Hottest Awards.
"""


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


def _send_vote_confirmation(email, saved_votes):
    if not email or not saved_votes:
        return

    vote_lines = [f"- {vote['category']}: {vote['nominee']}" for vote in saved_votes]
    vote_items_html = "".join(
        f"<li><strong>{vote['category']}</strong>: {vote['nominee']}</li>"
        for vote in saved_votes
    )

    text_message = "\n".join(
        [
            "ATL's Hottest Awards",
            "",
            "Thank you for voting.",
            "",
            "Your vote has been recorded for:",
            *vote_lines,
            "",
            "Important note: each voter may vote once per category per email address.",
            "",
            CONFIRMATION_AD_MESSAGE.strip(),
            "",
            "Thank you for supporting ATL's Hottest Awards.",
        ]
    )

    html_message = f"""
    <div style="margin:0;padding:0;background:#050505;color:#ffffff;font-family:Georgia,serif;">
      <div style="max-width:680px;margin:0 auto;padding:26px;">
        <div style="border:1px solid #ffd76a;border-radius:24px;overflow:hidden;background:linear-gradient(135deg,#000000,#3a0610);box-shadow:0 0 28px rgba(255,215,106,0.25);">
          <div style="padding:28px;background:linear-gradient(135deg,#000000,#7d0616 55%,#000000);border-bottom:1px solid rgba(255,215,106,0.55);">
            <p style="margin:0 0 8px;color:#ffd76a;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Official Vote Confirmation</p>
            <h1 style="margin:0;color:#ffffff;font-size:34px;line-height:1.05;text-shadow:0 0 18px rgba(255,215,106,0.45);">ATL's Hottest Awards</h1>
          </div>

          <div style="padding:28px;">
            <p style="font-size:18px;line-height:1.6;color:#ffffff;">Thank you for voting. Your vote has been recorded.</p>

            <div style="margin:20px 0;padding:18px;border:1px solid rgba(255,215,106,0.45);border-radius:18px;background:rgba(0,0,0,0.38);">
              <h2 style="margin:0 0 12px;color:#ffd76a;">Your Recorded Vote</h2>
              <ul style="margin:0;padding-left:20px;color:#ffffff;line-height:1.7;">
                {vote_items_html}
              </ul>
            </div>

            <p style="color:#f5dca0;line-height:1.6;"><strong>Voting rule:</strong> each voter may vote once per category per email address.</p>

            <div style="margin-top:24px;padding:18px;border:1px solid rgba(215,25,53,0.7);border-radius:18px;background:linear-gradient(135deg,rgba(215,25,53,0.24),rgba(0,0,0,0.35));">
              <p style="margin:0 0 8px;color:#ffd76a;letter-spacing:2px;text-transform:uppercase;font-weight:bold;">Sponsored Message</p>
              <p style="margin:0;color:#ffffff;line-height:1.6;">ATL's Hottest Awards supporters help keep the culture moving. Watch for featured offers, sponsor announcements, and red-carpet updates from ATL's Hottest Awards.</p>
            </div>

            <p style="margin-top:24px;color:#ffffff;">Thank you for supporting ATL's Hottest Awards.</p>
          </div>
        </div>
      </div>
    </div>
    """

    try:
        email_msg = EmailMultiAlternatives(
            subject="Your ATL's Hottest Awards vote was received",
            body=text_message,
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        email_msg.attach_alternative(html_message, "text/html")
        email_msg.send(fail_silently=True)
    except Exception:
        pass


def _create_vote(email, category, nominee, request):
    return Vote.objects.create(
        email=email,
        category=category,
        nominee=nominee,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


@require_http_methods(["GET"])
def landing_page(request):
    ballot_settings = BallotSettings.get_solo()

    featured_categories = []
    for category in Category.objects.for_ballot()[:6]:
        nominees = list(getattr(category, "prefetched_nominees", []))
        featured_categories.append(
            {
                "category": category,
                "nominee_count": len(nominees),
                "preview_nominees": nominees[:3],
            }
        )

    return render(
        request,
        "ballot/landing.html",
        {
            "settings": ballot_settings,
            "featured_categories": featured_categories,
        },
    )


@require_http_methods(["GET"])
def ballot_view(request):
    ballot_settings = BallotSettings.get_solo()

    categories_display = []
    for category in Category.objects.for_ballot():
        nominees = list(getattr(category, "prefetched_nominees", []))
        visible_count = min(len(nominees), 6)
        placeholder_count = max(0, 6 - visible_count)

        categories_display.append(
            {
                "category": category,
                "nominees": nominees,
                "placeholder_slots": range(placeholder_count),
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
            nominee = Nominee.objects.get(
                id=nominee_id,
                category=category,
                is_active=True,
                approval_status=Nominee.APPROVAL_APPROVED,
            )
        except (Category.DoesNotExist, Nominee.DoesNotExist):
            errors.append({"category": category_slug, "message": "Invalid nominee selection."})
            continue

        try:
            _create_vote(email, category, nominee, request)
            saved.append({"category": category.name, "nominee": nominee.name})
        except IntegrityError:
            skipped.append({"category": category.name, "message": "Already voted in this category."})

    if saved:
        _send_vote_confirmation(email, saved)

    return JsonResponse(
        {
            "message": "Your vote has been recorded." if saved else "No new votes were recorded.",
            "saved": saved,
            "skipped": skipped,
            "errors": errors,
        }
    )


@require_http_methods(["GET", "POST"])
@csrf_protect
def nominee_detail(request, nominee_id):
    nominee = get_object_or_404(
        Nominee.objects.select_related("category"),
        id=nominee_id,
        is_active=True,
        approval_status=Nominee.APPROVAL_APPROVED,
    )

    return render(request, "ballot/nominee_detail.html", {"nominee": nominee})


@require_POST
@csrf_protect
def vote_nominee(request, nominee_id):
    ballot_settings = BallotSettings.get_solo()

    nominee = get_object_or_404(
        Nominee.objects.select_related("category"),
        id=nominee_id,
        is_active=True,
        approval_status=Nominee.APPROVAL_APPROVED,
    )

    email = (request.POST.get("email") or "").strip().lower()

    if not ballot_settings.is_active():
        messages.error(request, f"Voting is currently {ballot_settings.status_label()}.")
        return redirect("nominee_detail", nominee_id=nominee.id)

    if not email:
        messages.error(request, "Email is required to vote.")
        return redirect("nominee_detail", nominee_id=nominee.id)

    try:
        _create_vote(email, nominee.category, nominee, request)
        saved = [{"category": nominee.category.name, "nominee": nominee.name}]
        _send_vote_confirmation(email, saved)
        request.session["vote_thank_you"] = {
            "email": email,
            "nominee": nominee.name,
            "category": nominee.category.name,
        }
        messages.success(
            request,
            f"Thank you for your vote. A special message is waiting for you at {email}.",
        )
    except IntegrityError:
        messages.warning(
            request,
            f"This email has already voted in {nominee.category.name}. One vote per category per email address.",
        )

    return redirect("nominee_detail", nominee_id=nominee.id)


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


@require_http_methods(["GET"])
def association_signup(request):
    return render(request, "ballot/association_signup.html")


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

    nominees = Nominee.objects.filter(is_active=True).select_related("category").order_by("name")
    return render(request, "ballot/association_join.html", {"nominees": nominees})


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def association_dashboard(request):
    profile, _created = AssociationProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "full_name": request.user.get_full_name() or request.user.get_username(),
            "notification_email": request.user.email,
        },
    )

    profile_form = AssociationProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
    )

    if request.method == "POST" and request.POST.get("form_name") == "association_profile":
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, "Your association member profile has been updated.")
            return redirect("assoc_dashboard")

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
            "profile": profile,
            "profile_form": profile_form,
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


@require_http_methods(["GET", "POST"])
@csrf_protect
def nominee_signup(request):
    form = NomineeSignupForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        nominee_name = form.cleaned_data["nominee_name"].strip()
        photo = form.cleaned_data.get("photo")
        created_nominees = []

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

            created_nominees.append(nominee)

            if request.user.is_authenticated:
                AssociationMembership.objects.get_or_create(
                    user=request.user,
                    nominee=nominee,
                    defaults={"is_active": False},
                )

        messages.success(
            request,
            "Nominee submitted. Staff will review and approve before it appears on the ballot.",
        )

        if request.user.is_authenticated:
            return redirect("assoc_dashboard")

        return redirect("ballot")

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



def healthz(request):
    return JsonResponse({"status": "ok", "app": "atlshottestawards"})
