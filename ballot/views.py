from __future__ import annotations
from django.http import HttpResponse
from .forms import EventSubmissionForm
from .models import AtlsHottestEvent
from django.urls import reverse
from io import BytesIO
# ballot/views.py
import logging

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

logger = logging.getLogger(__name__)
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.http import Http404, HttpResponse,  JsonResponse, HttpResponse, JsonResponse, Http404
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
from ballot.email_utils import absolute_url, extract_category_names_from_object, send_nominee_approved_email
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
def nomination_thank_you(request, nominee_id=None):
    nominees = []

    # Preferred path: nominee IDs stored immediately after successful submission.
    session_ids = request.session.get("last_nomination_ids") or []
    if session_ids:
        nominees = list(Nominee.objects.filter(pk__in=session_ids))
        nominee_order = {pk: i for i, pk in enumerate(session_ids)}
        nominees.sort(key=lambda item: nominee_order.get(item.pk, 999))

    # Backward-compatible path for older slug/numeric thank-you URLs.
    if not nominees and nominee_id:
        if str(nominee_id).isdigit():
            nominee = Nominee.objects.filter(pk=int(nominee_id)).first()
            if nominee:
                nominees = [nominee]

        if not nominees:
            nominee_field_names = {field.name for field in Nominee._meta.get_fields()}
            if "nominee_id" in nominee_field_names:
                nominee = Nominee.objects.filter(nominee_id=nominee_id).first()
                if nominee:
                    nominees = [nominee]

    if not nominees:
        return redirect("nominee_signup")

    nominee = nominees[0]

    category_names = []
    for item in nominees:
        category = getattr(item, "category", None)
        if category:
            category_names.append(str(getattr(category, "name", category)))

        categories = getattr(item, "categories", None)
        if categories is not None and hasattr(categories, "all"):
            category_names.extend([str(getattr(cat, "name", cat)) for cat in categories.all()])

    category_names = list(dict.fromkeys([name for name in category_names if name]))

    return render(request, "ballot/nomination_thank_you.html", {
        "nominee": nominee,
        "nominees": nominees,
        "category_names": category_names,
    })

@require_http_methods(["GET"])
def ballot_view(request):
    settings_obj, _created = BallotSettings.objects.get_or_create(pk=1)

    categories = (
        Category.objects.filter(is_active=True)
        .order_by("sort_order", "name")
    )

    selections = request.session.get("ballot_selections", {})

    category_blocks = []
    for category in categories:
        approved_count = Nominee.objects.filter(
            category=category,
            is_active=True,
            approval_status=Nominee.APPROVAL_APPROVED,
        ).count()

        selected_nominee = None
        selected_nominee_id = selections.get(category.slug)

        if selected_nominee_id:
            selected_nominee = Nominee.objects.filter(
                id=selected_nominee_id,
                category=category,
                is_active=True,
                approval_status=Nominee.APPROVAL_APPROVED,
            ).first()

        category_blocks.append(
            {
                "category": category,
                "approved_count": approved_count,
                "selected_nominee": selected_nominee,
            }
        )

    return render(
        request,
        "ballot/ballot.html",
        {
            "settings": settings_obj,
            "category_blocks": category_blocks,
            "selections": selections,
        },
    )


@require_POST
@csrf_protect
def submit_votes(request):

    closed = voting_closed_response(request)
    if closed:
        return closed

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

    return render(request, "ballot/nominee_detail.html", {**get_voting_status_context(), "nominee": nominee})


@require_POST
@csrf_protect
def vote_nominee(request, nominee_id):

    closed = voting_closed_response(request)
    if closed:
        return closed

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



def send_nomination_confirmation_email(nominator_name, nominator_email, nominee_name, category_names, request=None):
    """
    Sends a confirmation email to the person who submitted a nomination.
    Email delivery errors are logged but never block the nomination flow.
    """
    nominator_email = (nominator_email or "").strip()
    if not nominator_email:
        logger.warning("Nomination confirmation skipped because nominator_email was blank.")
        return False

    display_name = (nominator_name or "ATL's Hottest Fan").strip()
    nominee_name = (nominee_name or "your nominee").strip()
    categories_text = ", ".join(category_names or []) or "submitted category"

    subject = "Thank You For Nominating ATL's Hottest"

    plain_message = f"""Hi {display_name},

Thank you for nominating ATL's Hottest.

Nominee:
{nominee_name}

Category / Categories:
{categories_text}

Your nomination has been received and will be reviewed by the ATL's Hottest Awards Association team.

Advertise with ATL's Hottest and connect your brand with Atlanta culture, events, media, marketplace opportunities, awards, rewards, and more.

ATL's Hottest Awards Association
"""

    html_message = f"""
    <div style="font-family:Arial,sans-serif;background:#070707;color:#ffffff;padding:28px;border-radius:18px;">
      <h1 style="color:#ffd76a;margin:0 0 14px;">Thank You For Nominating!</h1>
      <p>Hi {display_name},</p>
      <p>Your nomination has been received and will be reviewed by the ATL's Hottest Awards Association team.</p>

      <div style="margin:22px 0;padding:18px;border:1px solid #ffd76a;border-radius:14px;background:#140207;">
        <p style="margin:0 0 8px;color:#ffd76a;font-weight:bold;">Nominee</p>
        <p style="margin:0 0 16px;font-size:20px;font-weight:bold;">{nominee_name}</p>

        <p style="margin:0 0 8px;color:#ffd76a;font-weight:bold;">Category / Categories</p>
        <p style="margin:0;font-size:18px;font-weight:bold;">{categories_text}</p>
      </div>

      <p style="font-size:18px;font-weight:bold;color:#ffd76a;">
        Advertise with ATL's Hottest.
      </p>

      <p>ATL's Hottest Awards Association</p>
    </div>
    """

    from_email = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", None)
        or "noreply@atlshottestawards.com"
    )

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=from_email,
            to=[nominator_email],
        )
        email.attach_alternative(html_message, "text/html")
        sent_count = email.send(fail_silently=False)
        logger.info("Nomination confirmation email sent to %s. Result=%s", nominator_email, sent_count)
        return sent_count
    except Exception:
        logger.exception("Nomination confirmation email failed for %s", nominator_email)
        return False


def nominee_signup(request):
    form = NomineeSignupForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        nominee_name = form.cleaned_data["nominee_name"].strip()
        photo = form.cleaned_data.get("photo")
        photo_name = getattr(photo, "name", "") if photo else ""
        photo_bytes = photo.read() if photo else None
        if photo and hasattr(photo, "seek"):
            photo.seek(0)
        created_nominees = []

        for category in form.cleaned_data["categories"]:
            nominee, _was_created = Nominee.objects.get_or_create(
                name=nominee_name,
                category=category,
                defaults={
                    "website": form.cleaned_data.get("website", ""),
                    "social_link": form.cleaned_data.get("social_link", ""),
                    "contact_email": form.cleaned_data.get("contact_email", ""),
                    "nominator_name": form.cleaned_data.get("nominator_name", ""),
                    "nominator_email": form.cleaned_data.get("nominator_email", ""),
                    "photo_submitted_at": timezone.now() if photo else None,
                    "approval_status": Nominee.APPROVAL_PENDING,
                    "is_active": True,
                },
            )

            # If nominee already existed, still keep latest nominator/contact info.
            nominee.website = form.cleaned_data.get("website", nominee.website)
            nominee.social_link = form.cleaned_data.get("social_link", nominee.social_link)
            nominee.contact_email = form.cleaned_data.get("contact_email", nominee.contact_email)
            nominee.nominator_name = form.cleaned_data.get("nominator_name", nominee.nominator_name)
            nominee.nominator_email = form.cleaned_data.get("nominator_email", nominee.nominator_email)

            if photo_bytes and photo_name:
                nominee.photo.save(photo_name, ContentFile(photo_bytes), save=False)
                nominee.photo_submitted_at = timezone.now()

            nominee.approval_status = Nominee.APPROVAL_PENDING
            nominee.is_active = True
            nominee.save()

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

        request.session["last_nomination_ids"] = [nom.pk for nom in created_nominees]
        request.session.modified = True

        confirmation_category_names = []
        for item in created_nominees:
            category = getattr(item, "category", None)
            if category:
                confirmation_category_names.append(str(getattr(category, "name", category)))

        confirmation_category_names = list(dict.fromkeys([name for name in confirmation_category_names if name]))

        # Confirmation email temporarily disabled for launch stability.
        # Nomination submit, save, photo upload, and thank-you redirect must never be blocked by email.
        pass


        return redirect("nomination_thank_you")

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


@require_http_methods(["GET"])
def ballot_category_view(request, category_slug):
    settings_obj, _created = BallotSettings.objects.get_or_create(pk=1)

    category = get_object_or_404(Category, slug=category_slug, is_active=True)

    nominees = list(
        Nominee.objects.filter(
            category=category,
            is_active=True,
            approval_status=Nominee.APPROVAL_APPROVED,
        ).order_by("name")
    )

    placeholder_count = max(0, 6 - len(nominees))
    selections = request.session.get("ballot_selections", {})
    selected_nominee_id = selections.get(category.slug)

    return render(
        request,
        "ballot/ballot_category.html",
        {
            "settings": settings_obj,
            "category": category,
            "nominees": nominees,
            "placeholder_count": placeholder_count,
            "placeholders": range(placeholder_count),
            "selected_nominee_id": selected_nominee_id,
        },
    )


@require_http_methods(["POST"])
@csrf_protect
def select_ballot_nominee(request, category_slug, nominee_id):

    closed = voting_closed_response(request)
    if closed:
        return closed

    category = get_object_or_404(Category, slug=category_slug, is_active=True)
    nominee = get_object_or_404(
        Nominee,
        id=nominee_id,
        category=category,
        is_active=True,
        approval_status=Nominee.APPROVAL_APPROVED,
    )

    selections = request.session.get("ballot_selections", {})
    selections[category.slug] = nominee.id
    request.session["ballot_selections"] = selections
    request.session.modified = True

    messages.success(request, f"You selected {nominee.name} for {category.name}.")

    action = request.POST.get("next_action", "review")

    if action == "continue":
        return redirect("ballot")

    return redirect("ballot_review")


@require_http_methods(["GET"])
def ballot_review(request):

    closed = voting_closed_response(request)
    if closed:
        return closed

    settings_obj, _created = BallotSettings.objects.get_or_create(pk=1)

    selections = request.session.get("ballot_selections", {})
    review_items = []

    categories = Category.objects.filter(is_active=True).order_by("sort_order", "name")

    for category in categories:
        nominee_id = selections.get(category.slug)
        if not nominee_id:
            continue

        nominee = Nominee.objects.filter(
            id=nominee_id,
            category=category,
            is_active=True,
            approval_status=Nominee.APPROVAL_APPROVED,
        ).first()

        if nominee:
            review_items.append(
                {
                    "category": category,
                    "nominee": nominee,
                }
            )

    return render(
        request,
        "ballot/ballot_review.html",
        {
            "settings": settings_obj,
            "review_items": review_items,
        },
    )


@require_http_methods(["POST"])
@csrf_protect
def submit_final_ballot(request):

    closed = voting_closed_response(request)
    if closed:
        return closed

    settings_obj, _created = BallotSettings.objects.get_or_create(pk=1)

    if settings_obj.status_label() != "active":
        messages.error(request, "Voting is not active yet. Please return when official voting opens.")
        return redirect("ballot_review")

    voter_email = request.POST.get("email", "").strip().lower()

    if not voter_email:
        messages.error(request, "Please enter your email address before submitting your final ballot.")
        return redirect("ballot_review")

    selections = request.session.get("ballot_selections", {})

    if not selections:
        messages.error(request, "Please select at least one nominee before submitting your final ballot.")
        return redirect("ballot")

    submitted_votes = []
    duplicate_votes = []
    unavailable_votes = []

    for category_slug, nominee_id in selections.items():
        category = Category.objects.filter(slug=category_slug, is_active=True).first()

        if not category:
            continue

        nominee = Nominee.objects.filter(
            id=nominee_id,
            category=category,
            is_active=True,
            approval_status=Nominee.APPROVAL_APPROVED,
        ).first()

        if not nominee:
            unavailable_votes.append(category.name)
            continue

        vote, created = Vote.objects.get_or_create(
            email=voter_email,
            category=category,
            defaults={"nominee": nominee},
        )

        if created:
            submitted_votes.append(
                {
                    "category": category,
                    "nominee": nominee,
                }
            )
        else:
            duplicate_votes.append(
                {
                    "category": category,
                    "nominee": vote.nominee,
                }
            )

    confirmation_payload = {
        "email": voter_email,
        "submitted_votes": [
            {"category": item["category"].name, "nominee": item["nominee"].name}
            for item in submitted_votes
        ],
        "duplicate_votes": [
            {"category": item["category"].name, "nominee": item["nominee"].name}
            for item in duplicate_votes
        ],
        "unavailable_votes": unavailable_votes,
    }

    request.session["ballot_confirmation"] = confirmation_payload
    request.session["ballot_selections"] = {}
    request.session.modified = True

    if submitted_votes or duplicate_votes:
        _send_final_ballot_confirmation(voter_email, submitted_votes, duplicate_votes)

    return redirect("ballot_confirmation")


@require_http_methods(["GET"])
def ballot_confirmation(request):
    confirmation = request.session.get("ballot_confirmation")

    return render(
        request,
        "ballot/ballot_confirmation.html",
        {
            "confirmation": confirmation,
        },
    )


def _send_final_ballot_confirmation(voter_email, submitted_votes, duplicate_votes=None):
    duplicate_votes = duplicate_votes or []

    submitted_lines = "\n".join(
        f"- {item['category'].name}: {item['nominee'].name}"
        for item in submitted_votes
    ) or "- No new votes were recorded."

    duplicate_lines = "\n".join(
        f"- {item['category'].name}: already recorded for {item['nominee'].name}"
        for item in duplicate_votes
    )

    duplicate_section = (
        f"\nPreviously recorded votes:\n{duplicate_lines}\n"
        if duplicate_lines
        else ""
    )

    subject = "Your ATL's Hottest Awards ballot was received"

    text_body = f"""ATL's Hottest Awards

Thank you for voting.

Your final ballot has been received for:
{submitted_lines}
{duplicate_section}
Important voting rule:
Each voter may vote once per category per email address.

Awards information:
Watch for red carpet updates, event announcements, sponsor offers, nominee highlights, and winner announcements from ATL's Hottest Awards.

Special message:
You've Been Chosen...

Some voters may be selected for special acknowledgements, prize opportunities, promotional offers, or awards-related updates when applicable.

Thank you for supporting ATL's Hottest Awards.
"""

    submitted_html = "".join(
        f"<li><strong>{item['category'].name}</strong>: {item['nominee'].name}</li>"
        for item in submitted_votes
    ) or "<li>No new votes were recorded.</li>"

    duplicate_html = "".join(
        f"<li><strong>{item['category'].name}</strong>: already recorded for {item['nominee'].name}</li>"
        for item in duplicate_votes
    )

    duplicate_html_section = (
        f"""
        <div style="margin:20px 0;padding:18px;border:1px solid rgba(255,215,106,0.35);border-radius:18px;background:rgba(0,0,0,0.3);">
          <h2 style="margin:0 0 12px;color:#ffd76a;">Previously Recorded Votes</h2>
          <ul style="margin:0;padding-left:20px;color:#ffffff;line-height:1.7;">{duplicate_html}</ul>
        </div>
        """
        if duplicate_html
        else ""
    )

    html_body = f"""
    <div style="margin:0;padding:0;background:#050505;color:#ffffff;font-family:Georgia,serif;">
      <div style="max-width:720px;margin:0 auto;padding:28px;">
        <div style="border:1px solid #ffd76a;border-radius:24px;overflow:hidden;background:linear-gradient(135deg,#000000,#3a0610);box-shadow:0 0 28px rgba(255,215,106,0.25);">
          <div style="padding:28px;background:linear-gradient(135deg,#000000,#7d0616 55%,#000000);border-bottom:1px solid rgba(255,215,106,0.55);">
            <p style="margin:0 0 8px;color:#ffd76a;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Official Ballot Confirmation</p>
            <h1 style="margin:0;color:#ffffff;font-size:34px;line-height:1.05;">ATL's Hottest Awards</h1>
          </div>

          <div style="padding:28px;">
            <p style="font-size:18px;line-height:1.6;color:#ffffff;">Thank you for voting. Your final ballot has been received.</p>

            <div style="margin:20px 0;padding:18px;border:1px solid rgba(255,215,106,0.45);border-radius:18px;background:rgba(0,0,0,0.38);">
              <h2 style="margin:0 0 12px;color:#ffd76a;">Your Recorded Ballot</h2>
              <ul style="margin:0;padding-left:20px;color:#ffffff;line-height:1.7;">{submitted_html}</ul>
            </div>

            {duplicate_html_section}

            <div style="margin:20px 0;padding:18px;border:1px solid rgba(215,25,53,0.7);border-radius:18px;background:linear-gradient(135deg,rgba(215,25,53,0.24),rgba(0,0,0,0.35));">
              <p style="margin:0 0 8px;color:#ffd76a;letter-spacing:2px;text-transform:uppercase;font-weight:bold;">You've Been Chosen...</p>
              <p style="margin:0;color:#ffffff;line-height:1.6;">Some voters may be selected for special acknowledgements, prize opportunities, promotional offers, or awards-related updates when applicable.</p>
            </div>

            <p style="color:#f5dca0;line-height:1.6;"><strong>Voting rule:</strong> each voter may vote once per category per email address.</p>
            <p style="color:#ffffff;">Watch for red carpet updates, event announcements, sponsor offers, nominee highlights, and winner announcements.</p>
          </div>
        </div>
      </div>
    </div>
    """

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
        to=[voter_email],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=True)
@require_http_methods(["GET"])
def atl_tv(request):
    return render(request, "ballot/atl_tv.html")

def _send_real_nominee_approval_email(request_obj, nominee_obj=None, temporary_password=None):
    """
    Send polished nominee approval email from staff approval flow.

    This function is intentionally defensive because request/nominee field names
    can differ across versions of the app.
    """
    obj = nominee_obj or request_obj

    to_email = (
        getattr(request_obj, "contact_email", None)
        or getattr(request_obj, "email", None)
        or getattr(request_obj, "nominee_email", None)
        or getattr(obj, "contact_email", None)
        or getattr(obj, "email", None)
        or ""
    )

    if not to_email:
        return

    nominee_name = (
        getattr(obj, "display_name", None)
        or getattr(obj, "name", None)
        or getattr(obj, "nominee_name", None)
        or getattr(request_obj, "display_name", None)
        or getattr(request_obj, "name", None)
        or getattr(request_obj, "nominee_name", None)
        or "Nominee"
    )

    username = to_email

    categories = []
    for source in [request_obj, nominee_obj]:
        if source is None:
            continue
        for category_name in extract_category_names_from_object(source):
            if category_name not in categories:
                categories.append(category_name)

    nominee_url = None
    try:
        if nominee_obj and hasattr(nominee_obj, "get_absolute_url"):
            nominee_url = absolute_url(nominee_obj.get_absolute_url())
        elif nominee_obj and getattr(nominee_obj, "slug", None):
            nominee_url = absolute_url(f"/nominee/{nominee_obj.slug}/")
    except Exception:
        nominee_url = None

    send_nominee_approved_email(
        to_email=to_email,
        nominee_name=nominee_name,
        username=username,
        temporary_password=temporary_password,
        categories=categories,
        login_url=absolute_url("/accounts/login/"),
        dashboard_url=absolute_url("/association/dashboard/"),
        nominee_url=nominee_url,
    )




# =========================================================
# ATL's Hottest Advertise Command Center
# Powered By The MajesticMall Megaverse Advertising Platform
# =========================================================

def advertise_command_center(request):
    from django.contrib import messages
    from django.shortcuts import render, redirect
    from .forms import AdvertisingInquiryForm

    if request.method == "POST":
        form = AdvertisingInquiryForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save()
                return redirect("advertise_thank_you")
            except Exception as exc:
                messages.error(request, f"Your inquiry could not be submitted yet: {exc}")
        else:
            messages.error(request, "Please review the form and try again.")
    else:
        form = AdvertisingInquiryForm()

    return render(request, "ballot/advertise_command_center.html", {"form": form})


def advertise_thank_you(request):
    from django.shortcuts import render
    return render(request, "ballot/advertise_thank_you.html")


# =========================================================
# ATL'S HOTTEST AUTOPILOT MEMBERSHIP VIEWS
# =========================================================

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils import timezone


def membership_plans(request):
    plans = (
        MembershipPlan.objects
        .filter(is_active=True)
        .prefetch_related("benefits", "rewards")
        .order_by("display_order", "price", "name")
    )

    current_membership = None
    if request.user.is_authenticated:
        current_membership = getattr(request.user, "atl_membership", None)

    return render(request, "ballot/membership_plans.html", {
        "plans": plans,
        "current_membership": current_membership,
    })


def membership_plan_detail(request, slug):
    plan = get_object_or_404(
        MembershipPlan.objects.prefetch_related("benefits", "rewards"),
        slug=slug,
        is_active=True,
    )

    current_membership = None
    if request.user.is_authenticated:
        current_membership = getattr(request.user, "atl_membership", None)

    return render(request, "ballot/membership_plan_detail.html", {
        "plan": plan,
        "current_membership": current_membership,
    })


@login_required
def choose_membership_plan(request, slug):
    plan = get_object_or_404(MembershipPlan, slug=slug, is_active=True)

    membership, created = UserMembership.objects.get_or_create(
        user=request.user,
        defaults={
            "plan": plan,
            "status": "active" if plan.is_free else "pending",
            "started_at": timezone.now() if plan.is_free else None,
        }
    )

    if not created:
        membership.plan = plan
        membership.status = "active" if plan.is_free else "pending"
        if plan.is_free and not membership.started_at:
            membership.started_at = timezone.now()
        membership.save()

    # Temporary autopilot payment bridge:
    # If the plan has an external payment URL, send them there.
    # Later we replace this with Stripe/PayPal/Coinbase checkout.
    if not plan.is_free and plan.external_checkout_url:
        return redirect(plan.external_checkout_url)

    return redirect("membership_dashboard")


@login_required
def membership_dashboard(request):
    membership = getattr(request.user, "atl_membership", None)

    return render(request, "ballot/membership_dashboard.html", {
        "membership": membership,
    })


# =========================================================
# ATL'S HOTTEST AUTOPILOT MEMBERSHIP VIEWS
# =========================================================

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils import timezone
from .models import MembershipPlan, MembershipBenefit, MembershipReward, UserMembership
from .models import VotingCampaign


def membership_plans(request):
    plans = (
        MembershipPlan.objects
        .filter(is_active=True)
        .prefetch_related("benefits", "rewards")
        .order_by("display_order", "price", "name")
    )

    current_membership = None
    if request.user.is_authenticated:
        current_membership = getattr(request.user, "atl_membership", None)

    return render(request, "ballot/membership_plans.html", {
        "plans": plans,
        "current_membership": current_membership,
    })


def membership_plan_detail(request, slug):
    plan = get_object_or_404(
        MembershipPlan.objects.prefetch_related("benefits", "rewards"),
        slug=slug,
        is_active=True,
    )

    current_membership = None
    if request.user.is_authenticated:
        current_membership = getattr(request.user, "atl_membership", None)

    return render(request, "ballot/membership_plan_detail.html", {
        "plan": plan,
        "current_membership": current_membership,
    })


@login_required
def choose_membership_plan(request, slug):
    plan = get_object_or_404(MembershipPlan, slug=slug, is_active=True)

    membership, created = UserMembership.objects.get_or_create(
        user=request.user,
        defaults={
            "plan": plan,
            "status": "active" if plan.is_free else "pending",
            "started_at": timezone.now() if plan.is_free else None,
        }
    )

    if not created:
        membership.plan = plan
        membership.status = "active" if plan.is_free else "pending"
        if plan.is_free and not membership.started_at:
            membership.started_at = timezone.now()
        membership.save()

    # Temporary autopilot payment bridge:
    # If the plan has an external payment URL, send them there.
    # Later we replace this with Stripe/PayPal/Coinbase checkout.
    if not plan.is_free and plan.external_checkout_url:
        return redirect(plan.external_checkout_url)

    return redirect("membership_dashboard")


@login_required
def membership_dashboard(request):
    membership = getattr(request.user, "atl_membership", None)

    return render(request, "ballot/membership_dashboard.html", {
        "membership": membership,
    })


# =========================================================
# VOTING CAMPAIGN CONTROL HELPERS
# =========================================================

def get_active_voting_campaign():
    try:
        return VotingCampaign.objects.filter(is_active_campaign=True).order_by("-created_at").first()
    except Exception:
        return None


def is_voting_currently_open():
    campaign = get_active_voting_campaign()

    # If no campaign has been configured yet, keep legacy voting behavior open.
    # Once admin creates a VotingCampaign, the campaign controls take over.
    if campaign is None:
        return True, None

    return campaign.is_voting_open, campaign



def get_voting_status_context():
    voting_open, campaign = is_voting_currently_open()
    return {
        "voting_open": voting_open,
        "active_campaign": campaign,
    }


def voting_closed_response(request):
    voting_open, campaign = is_voting_currently_open()

    if voting_open:
        return None

    return render(request, "ballot/voting_closed.html", {
        "campaign": campaign,
    })




def visible_category_queryset():
    """
    Return public-facing categories only.
    Hides old archived categories from the ballot pages.
    """
    from .models import Category

    qs = Category.objects.all()
    field_names = {field.name for field in Category._meta.fields}

    if "is_active" in field_names:
        qs = qs.filter(is_active=True)
    elif "active" in field_names:
        qs = qs.filter(active=True)
    elif "is_public" in field_names:
        qs = qs.filter(is_public=True)

    qs = qs.exclude(name__istartswith="Archived - ")

    order_fields = []
    if "group" in field_names:
        order_fields.append("group")
    if "display_order" in field_names:
        order_fields.append("display_order")
    if "name" in field_names:
        order_fields.append("name")

    if order_fields:
        qs = qs.order_by(*order_fields)

    return qs


# =========================================================
# CLEAN BALLOT PREVIEW VIEW
# Ensures /ballot/ always shows categories while voting is closed.
# =========================================================

def ballot_view(request):
    from .models import Category

    try:
        from .models import BallotSettings
        settings_obj, _created = BallotSettings.objects.get_or_create(pk=1)
    except Exception:
        settings_obj = None

    order_fields = []
    category_field_names = {field.name for field in Category._meta.fields}

    if "group" in category_field_names:
        order_fields.append("group")

    if "display_order" in category_field_names:
        order_fields.append("display_order")

    if "name" in category_field_names:
        order_fields.append("name")

    if order_fields:
        categories = visible_category_queryset()
    else:
        categories = visible_category_queryset()

    return render(request, "ballot/ballot.html", {
        "categories": categories,
        "settings": settings_obj,
    })


# =========================================================
# HOME / LANDING VIEW SAFETY ALIAS
# Restores homepage route after URL cleanup.
# =========================================================

def landing(request):
    return render(request, "ballot/landing.html")


# =========================================================
# ATL'S HOTTEST MEMBERSHIP PAYMENT CENTER
# Sends paid package selections to a payment/intake center.
# =========================================================

def membership_payment_center(request, slug):
    from django.shortcuts import get_object_or_404, render
    from .models import MembershipPlan

    plan = get_object_or_404(
        MembershipPlan.objects.prefetch_related("benefits", "rewards"),
        slug=slug,
        is_active=True,
    )

    return render(request, "ballot/membership_payment_center.html", {
        "plan": plan,
    })


@login_required
def choose_membership_plan(request, slug):
    from django.shortcuts import get_object_or_404, redirect
    from .models import MembershipPlan, UserMembership

    plan = get_object_or_404(MembershipPlan, slug=slug, is_active=True)

    # Free plans can still activate immediately.
    if plan.is_free:
        UserMembership.objects.update_or_create(
            user=request.user,
            defaults={
                "plan": plan,
                "status": "active",
                "payment_reference": "free-plan",
            },
        )
        return redirect("membership_dashboard")

    # Paid plans now go to the Payment Center first.
    return redirect("membership_payment_center", slug=plan.slug)


# =========================================================
# ATL'S HOTTEST MARKETPLACE
# Merchandise, badges, add-ons, advertising bundles, and member upgrades.
# =========================================================

def atls_hottest_marketplace(request):
    marketplace_items = [
        {
            "category": "Merchandise",
            "name": "I Am ATL’s Hottest T-Shirt",
            "price": "Coming Soon",
            "description": "Official ATL’s Hottest member merchandise for fans, nominees, creators, and supporters.",
        },
        {
            "category": "Recognition",
            "name": "I Am ATL’s Hottest Badge",
            "price": "Coming Soon",
            "description": "Digital and promotional badge options for members, nominees, creators, businesses, and supporters.",
        },
        {
            "category": "Merchandise",
            "name": "ATL’s Hottest Fan",
            "price": "Coming Soon",
            "description": "Branded fan merchandise for events, red carpet moments, community activations, and promotional giveaways.",
        },
        {
            "category": "Advertising",
            "name": "3-Day Billboard/Banner Advertising Package",
            "price": "Coming Soon",
            "description": "Short-run advertising bundle for announcements, music releases, product drops, event promotion, and brand visibility.",
        },
        {
            "category": "Advertising",
            "name": "7-Day Spotlight Advertising Bundle",
            "price": "Coming Soon",
            "description": "One-week promotional package for billboard, banner, category, and ATL’s Hottest visibility opportunities.",
        },
        {
            "category": "Advertising",
            "name": "ATL TV Sponsor Add-On",
            "price": "Coming Soon",
            "description": "Sponsor visibility connected to ATL TV programming, nominee highlights, interviews, and promotional content.",
        },
        {
            "category": "Seller Tools",
            "name": "Product Promotion Add-On",
            "price": "Coming Soon",
            "description": "Add-on for members preparing to sell products, services, offers, tickets, music, media, or branded merchandise.",
        },
    ]

    return render(request, "ballot/atls_hottest_marketplace.html", {
        "marketplace_items": marketplace_items,
    })


def about_atls_hottest(request):
    return render(request, "ballot/about_atls_hottest.html")


def events_whats_happening(request):
    approved_events = AtlsHottestEvent.objects.filter(status="approved").order_by("starts_at", "title")

    live_today_events = approved_events.filter(show_today=True)
    featured_events = approved_events.filter(is_featured=True)
    regular_events = approved_events.filter(category="events")
    festival_events = approved_events.filter(category="festivals")
    nightlife_events = approved_events.filter(category="nightlife")
    promotion_events = approved_events.filter(category="special_promotions")

    return render(request, "ballot/events_whats_happening.html", {
        "today_date": timezone.localdate(),
        "timezone_label": "Eastern Time",
        "approved_events": approved_events,
        "live_today_events": live_today_events,
        "featured_events": featured_events,
        "regular_events": regular_events,
        "festival_events": festival_events,
        "nightlife_events": nightlife_events,
        "promotion_events": promotion_events,
    })


def event_submit(request):
    if request.method == "POST":
        form = EventSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.status = "pending"
            event.save()
            messages.success(request, "Your event has been submitted for review.")
            return redirect("event_submitted", slug=event.slug)
    else:
        form = EventSubmissionForm()

    return render(request, "ballot/event_submit.html", {"form": form})


def sample_event_detail(request, slug):
    event = SAMPLE_EVENT_CARDS.get(slug)

    if event is None:
        raise Http404("Sample event not found.")

    return render(request, "ballot/sample_event_detail.html", {
        "event": event,
        "slug": slug,
        "today_date": timezone.localdate(),
        "timezone_label": "Eastern Time",
    })



def event_submitted(request, slug):
    event = get_object_or_404(AtlsHottestEvent, slug=slug)
    return render(request, "ballot/event_submitted.html", {
        "event": event,
        "event_url": request.build_absolute_uri(reverse("event_detail", kwargs={"slug": event.slug})),
    })


def event_detail(request, slug):
    event = get_object_or_404(AtlsHottestEvent, slug=slug)

    if event.status != "approved" and not request.user.is_staff:
        messages.info(request, "This event has been submitted and is pending review.")

    return render(request, "ballot/event_detail.html", {
        "event": event,
        "event_url": request.build_absolute_uri(reverse("event_detail", kwargs={"slug": event.slug})),
    })


def event_qr_code(request, slug):
    event = get_object_or_404(AtlsHottestEvent, slug=slug)

    import qrcode

    event_url = request.build_absolute_uri(reverse("event_detail", kwargs={"slug": event.slug}))
    img = qrcode.make(event_url)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type="image/png")


# ============================================================
# ATL'S HOTTEST - MOBILE EVENT APPROVAL CENTER
# ============================================================

@staff_member_required
def event_approval_center(request):
    selected_status = request.GET.get("status", "pending")

    valid_statuses = {"pending", "approved", "rejected", "all"}
    if selected_status not in valid_statuses:
        selected_status = "pending"

    events = AtlsHottestEvent.objects.all()

    if selected_status != "all":
        events = events.filter(status=selected_status)

    events = events.order_by("-submitted_at", "starts_at")

    counts = {
        "pending": AtlsHottestEvent.objects.filter(status="pending").count(),
        "approved": AtlsHottestEvent.objects.filter(status="approved").count(),
        "rejected": AtlsHottestEvent.objects.filter(status="rejected").count(),
        "all": AtlsHottestEvent.objects.count(),
    }

    return render(
        request,
        "ballot/event_approval_center.html",
        {
            "events": events,
            "selected_status": selected_status,
            "counts": counts,
        },
    )


@staff_member_required
@require_POST
def event_approval_action(request, pk):
    event = get_object_or_404(AtlsHottestEvent, pk=pk)
    action = request.POST.get("action", "").strip()

    if action == "approve":
        event.status = "approved"
        event.save(update_fields=["status", "updated_at"])
        messages.success(request, f"{event.title} has been approved.")

    elif action == "reject":
        event.status = "rejected"
        event.show_today = False
        event.is_featured = False
        event.show_on_homepage = False
        event.save(
            update_fields=[
                "status",
                "show_today",
                "is_featured",
                "show_on_homepage",
                "updated_at",
            ]
        )
        messages.success(request, f"{event.title} has been rejected.")

    elif action == "toggle_featured":
        event.is_featured = not event.is_featured
        event.save(update_fields=["is_featured", "updated_at"])

        state = "ON" if event.is_featured else "OFF"
        messages.success(
            request,
            f"Featured placement for {event.title}: {state}.",
        )

    elif action == "toggle_today":
        event.show_today = not event.show_today
        event.save(update_fields=["show_today", "updated_at"])

        state = "ON" if event.show_today else "OFF"
        messages.success(
            request,
            f"Show Today for {event.title}: {state}.",
        )

    elif action == "save_homepage_promo":
        from datetime import timedelta
        from decimal import Decimal, InvalidOperation
        from django.utils.dateparse import parse_datetime

        payment_status = request.POST.get(
            "homepage_payment_status",
            "not_required",
        ).strip()

        package = request.POST.get(
            "homepage_package",
            "",
        ).strip()

        amount_raw = request.POST.get(
            "homepage_amount_paid",
            "0",
        ).strip() or "0"

        start_raw = request.POST.get(
            "homepage_promotion_start",
            "",
        ).strip()

        end_raw = request.POST.get(
            "homepage_promotion_end",
            "",
        ).strip()

        requested_homepage = (
            request.POST.get("show_on_homepage") == "on"
        )

        valid_payment_statuses = {
            choice[0]
            for choice in AtlsHottestEvent.HOMEPAGE_PAYMENT_STATUS_CHOICES
        }

        valid_packages = {
            choice[0]
            for choice in AtlsHottestEvent.HOMEPAGE_PACKAGE_CHOICES
        }

        if payment_status not in valid_payment_statuses:
            messages.error(request, "Invalid payment status.")
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        if package not in valid_packages:
            messages.error(request, "Invalid homepage promotion package.")
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Amount paid must be a valid dollar amount.")
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        if amount < 0:
            messages.error(request, "Amount paid cannot be negative.")
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        def parse_local_datetime(value):
            if not value:
                return None

            parsed = parse_datetime(value)

            if parsed and timezone.is_naive(parsed):
                parsed = timezone.make_aware(
                    parsed,
                    timezone.get_current_timezone(),
                )

            return parsed

        start_at = parse_local_datetime(start_raw)
        end_at = parse_local_datetime(end_raw)

        if start_raw and start_at is None:
            messages.error(request, "Promotion start date/time is invalid.")
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        if end_raw and end_at is None:
            messages.error(request, "Promotion end date/time is invalid.")
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        package_durations = {
            "24_hours": timedelta(hours=24),
            "3_days": timedelta(days=3),
            "7_days": timedelta(days=7),
        }

        if package in package_durations and start_at:
            end_at = start_at + package_durations[package]

        if package == "custom":
            if start_at and not end_at:
                messages.error(
                    request,
                    "Custom promotions require an end date/time.",
                )
                return redirect(
                    f"{reverse('event_approval_center')}?status="
                    f"{request.POST.get('return_status', 'pending')}"
                )

        if start_at and end_at and end_at <= start_at:
            messages.error(
                request,
                "Promotion end must be later than promotion start.",
            )
            return redirect(
                f"{reverse('event_approval_center')}?status="
                f"{request.POST.get('return_status', 'pending')}"
            )

        allow_homepage = requested_homepage

        if requested_homepage and event.status != "approved":
            allow_homepage = False
            messages.warning(
                request,
                "Homepage promotion was saved but NOT activated because "
                "the event is not approved.",
            )

        elif requested_homepage and payment_status not in {"paid", "comp"}:
            allow_homepage = False
            messages.warning(
                request,
                "Homepage promotion was saved but NOT activated because "
                "payment must be Paid or Complimentary.",
            )

        elif requested_homepage and not package:
            allow_homepage = False
            messages.warning(
                request,
                "Homepage promotion was saved but NOT activated because "
                "a promotion package is required.",
            )

        elif requested_homepage and (not start_at or not end_at):
            allow_homepage = False
            messages.warning(
                request,
                "Homepage promotion was saved but NOT activated because "
                "a start and end time are required.",
            )

        event.homepage_payment_status = payment_status
        event.homepage_package = package
        event.homepage_amount_paid = amount
        event.homepage_promotion_start = start_at
        event.homepage_promotion_end = end_at
        event.show_on_homepage = allow_homepage

        event.save(
            update_fields=[
                "homepage_payment_status",
                "homepage_package",
                "homepage_amount_paid",
                "homepage_promotion_start",
                "homepage_promotion_end",
                "show_on_homepage",
                "updated_at",
            ]
        )

        if allow_homepage:
            messages.success(
                request,
                f"Homepage promotion activated for {event.title}.",
            )
        elif not requested_homepage:
            messages.success(
                request,
                f"Homepage promotion settings saved for {event.title}.",
            )

    else:
        messages.error(request, "Unknown event action.")

    return redirect(
        f"{reverse('event_approval_center')}?status="
        f"{request.POST.get('return_status', 'pending')}"
    )
