from __future__ import annotations
import secrets

# ballot/models.py

import uuid
import warnings
import re
from urllib.parse import urlsplit, urlunsplit
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import models
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum
from django.utils.text import slugify
from ballot.email_utils import absolute_url, send_nominee_approved_email


# ---------------------------------------------------------------------
# Secure image upload validation
# ---------------------------------------------------------------------

MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_PIXELS = 40_000_000

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


def validate_safe_image_upload(uploaded_file):
    """
    Validate all user-supplied artwork as a genuine, reasonably sized image.

    Security rules:
    - JPG/JPEG, PNG, and WEBP only
    - 10 MB maximum
    - actual image bytes must decode successfully
    - file extension, MIME type (when supplied), and decoded format must agree
    - reject images with excessive pixel counts
    """

    if not uploaded_file:
        return

    filename = getattr(uploaded_file, "name", "") or ""
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            "Unsupported image type. Please upload a JPG, JPEG, PNG, or WEBP image."
        )

    content_type = getattr(uploaded_file, "content_type", None)
    if content_type:
        content_type = content_type.lower()
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValidationError(
                "Unsupported image type. Please upload a JPG, JPEG, PNG, or WEBP image."
            )

    try:
        # FieldFile values may need to be opened explicitly.
        if getattr(uploaded_file, "closed", False) and hasattr(uploaded_file, "open"):
            uploaded_file.open("rb")

        uploaded_file.seek(0)
        raw = uploaded_file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        uploaded_file.seek(0)

        if len(raw) > MAX_IMAGE_UPLOAD_BYTES:
            raise ValidationError("Image files may not exceed 10 MB.")

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(BytesIO(raw)) as image:
                detected_format = (image.format or "").upper()
                width, height = image.size

                if detected_format not in ALLOWED_IMAGE_FORMATS:
                    raise ValidationError(
                        "Unsupported image type. Please upload a JPG, JPEG, PNG, or WEBP image."
                    )

                if width <= 0 or height <= 0:
                    raise ValidationError("The uploaded image is invalid.")

                if width * height > MAX_IMAGE_PIXELS:
                    raise ValidationError(
                        "This image is too large in dimensions. Please use a smaller image."
                    )

                image.verify()

    except ValidationError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValidationError(
            "The uploaded file could not be verified as a safe image."
        )

    # Make the upload available to Django again after validation.
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------
# Ballot settings
# ---------------------------------------------------------------------

class BallotSettings(models.Model):
    """
    Singleton model to control voting availability.

    Admin can:
    - schedule voting with start_at / end_at
    - pause voting temporarily
    - stop voting completely
    """

    start_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When voting becomes active. Leave blank to start immediately.",
    )
    end_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When voting ends. Leave blank for no scheduled end.",
    )
    paused = models.BooleanField(
        default=False,
        help_text="Temporarily pause voting without changing dates.",
    )
    stopped = models.BooleanField(
        default=False,
        help_text="Hard-stop voting immediately.",
    )
    announcement = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional public message/banner text.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ballot Settings"
        verbose_name_plural = "Ballot Settings"

    def __str__(self) -> str:
        return "Ballot Settings"

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "End date/time must be after start date/time."})

    @classmethod
    def get_solo(cls) -> "BallotSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def status_label(self) -> str:
        """
        Returns:
        stopped | paused | scheduled | ended | active
        """
        now = timezone.now()

        if self.stopped:
            return "stopped"
        if self.paused:
            return "paused"
        if self.start_at and now < self.start_at:
            return "scheduled"
        if self.end_at and now >= self.end_at:
            return "ended"
        return "active"

    def is_active(self) -> bool:
        return self.status_label() == "active"


# ---------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------

class CategoryQuerySet(models.QuerySet):
    def for_ballot(self, *, campaign):
        return (
            self.filter(is_active=True)
            .order_by("group", "sort_order", "name")
            .prefetch_related(
                models.Prefetch(
                    "nominees",
                    queryset=Nominee.objects.filter(
                        campaign=campaign,
                        is_active=True,
                        approval_status=Nominee.APPROVAL_APPROVED,
                    ).order_by("name"),
                    to_attr="prefetched_nominees",
                )
            )
        )


class Category(models.Model):
    GROUP_CHOICES = (
        ("Entertainment", "Entertainment"),
        ("Events", "Events"),
        ("Venues", "Venues"),
        ("Media", "Media"),
        ("Personalities", "Personalities"),
        ("Professionals", "Professionals"),
        ("Fashion & Beauty", "Fashion & Beauty"),
        ("Community", "Community"),
        ("Icons / Legends / VIPs", "Icons / Legends / VIPs"),
    )

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    group = models.CharField(max_length=40, choices=GROUP_CHOICES, default="Entertainment")
    description = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = CategoryQuerySet.as_manager()

    class Meta:
        ordering = ["group", "sort_order", "name"]
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

    @property
    def active_nominee_count(self) -> int:
        return self.nominees.filter(is_active=True).count()


# ---------------------------------------------------------------------
# Nominees
# ---------------------------------------------------------------------

class NomineeQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, approval_status=Nominee.APPROVAL_APPROVED)

    def pending(self):
        return self.filter(is_active=True, approval_status=Nominee.APPROVAL_PENDING)

    def rejected(self):
        return self.filter(approval_status=Nominee.APPROVAL_REJECTED)

    def for_ballot(self):
        return self.active().select_related("category").order_by("category__name", "name")


class Nominee(models.Model):

    nominator_name = models.CharField(
        "ATL's Hottest Fan (Name of Person Nominating)",
        max_length=160,
        blank=True,
    )
    nominator_email = models.EmailField(
        "Valid Email Address",
        blank=True,
    )

    APPROVAL_PENDING = "pending"
    APPROVAL_APPROVED = "approved"
    APPROVAL_REJECTED = "rejected"

    APPROVAL_CHOICES = (
        (APPROVAL_PENDING, "Pending"),
        (APPROVAL_APPROVED, "Approved"),
        (APPROVAL_REJECTED, "Rejected"),
    )

    id = models.SlugField(primary_key=True, max_length=64)
    name = models.CharField(max_length=160)

    campaign = models.ForeignKey(
        "VotingCampaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="nominees",
        help_text="Awards cycle associated with this nominee record.",
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="nominees",
    )

    photo = models.ImageField(
        upload_to="nominees/",
        blank=True,
        null=True,
        validators=[validate_safe_image_upload],
    )
    photo_submitted_at = models.DateTimeField(blank=True, null=True)

    website = models.URLField(blank=True, default="")
    social_link = models.URLField(blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

    upload_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_CHOICES,
        default=APPROVAL_APPROVED,
        help_text="Only approved nominees appear on the public ballot.",
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NomineeQuerySet.as_manager()

    class Meta:
        ordering = ["category__name", "name"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "name", "category"],
                name="unique_nominee_name_per_campaign_category",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} — {self.category.name}"

    def save(self, *args, **kwargs):
        if not self.id:
            base = f"{slugify(self.name) or 'nominee'}-{self.category.slug or slugify(self.category.name)}"
            base = base[:64]
            candidate = base
            i = 2
            while Nominee.objects.filter(pk=candidate).exclude(pk=self.pk).exists():
                suffix = f"-{i}"
                candidate = base[: 64 - len(suffix)] + suffix
                i += 1
            self.id = candidate
        super().save(*args, **kwargs)

    @staticmethod
    def normalize_identity_name(value):
        """
        Normalize harmless formatting differences without deciding that
        professional/stage titles make two people the same person.
        """
        value = (value or "").strip().casefold()
        value = re.sub(r"[.,'’\"`]", "", value)
        value = re.sub(r"[-_/]+", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    @staticmethod
    def normalize_identity_email(value):
        return (value or "").strip().casefold()

    @staticmethod
    def normalize_identity_url(value):
        """
        Normalize website/social URLs for identity comparison only.
        """
        value = (value or "").strip()
        if not value:
            return ""

        candidate = value
        if "://" not in candidate:
            candidate = "https://" + candidate

        try:
            parts = urlsplit(candidate)
        except ValueError:
            return value.casefold().rstrip("/")

        host = (parts.hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]

        path = re.sub(r"/+", "/", parts.path or "").rstrip("/")

        # Ignore scheme, query string and fragments for identity matching.
        return urlunsplit(("", host, path, "", "")).lstrip("//")

    @classmethod
    def find_identity_match(
        cls,
        *,
        category,
        campaign,
        name,
        contact_email="",
        social_link="",
        website="",
    ):
        """
        Return an existing nominee/category record only when there is
        sufficient evidence that the submission represents that nominee.

        Exact normalized names are safe to reuse.

        Different name strings require matching digital identity evidence
        (email, social profile, or website). Titles alone never force a merge.
        """
        candidates = cls.objects.filter(
            category=category,
            campaign=campaign,
        )

        normalized_name = cls.normalize_identity_name(name)
        normalized_email = cls.normalize_identity_email(contact_email)
        normalized_social = cls.normalize_identity_url(social_link)
        normalized_website = cls.normalize_identity_url(website)

        # First: harmless name-format differences.
        for candidate in candidates:
            if (
                cls.normalize_identity_name(candidate.name)
                == normalized_name
            ):
                return candidate

        # Second: strong digital identity evidence.
        for candidate in candidates:
            candidate_email = cls.normalize_identity_email(
                candidate.contact_email
            )
            candidate_social = cls.normalize_identity_url(
                candidate.social_link
            )
            candidate_website = cls.normalize_identity_url(
                candidate.website
            )

            email_match = bool(
                normalized_email
                and candidate_email
                and normalized_email == candidate_email
            )

            social_match = bool(
                normalized_social
                and candidate_social
                and normalized_social == candidate_social
            )

            website_match = bool(
                normalized_website
                and candidate_website
                and normalized_website == candidate_website
            )

            if email_match or social_match or website_match:
                return candidate

        return None

    @property
    def photo_url(self) -> str:
        if self.photo:
            return self.photo.url
        return ""

    def get_upload_url(self) -> str:
        return reverse("nominee_upload", kwargs={"token": self.upload_token})


    def approve(self):
        self.approval_status = self.APPROVAL_APPROVED
        self.approved_at = timezone.now()
        self.rejected_at = None
        self.is_active = True
        self.save(update_fields=["approval_status", "approved_at", "rejected_at", "is_active", "updated_at"])

        self.send_approval_notice()

    def reject(self):
        self.approval_status = self.APPROVAL_REJECTED
        self.rejected_at = timezone.now()
        self.save(update_fields=["approval_status", "rejected_at", "updated_at"])

    def send_approval_email(self, user, temporary_password=None, account_created=False):
        """
        Send polished nominee approval / nomination email.

        This email confirms the nominee is approved, congratulates them,
        includes their nominated category, and gives account/dashboard access.
        """
        if not self.contact_email:
            return

        nominee_url = None
        try:
            nominee_url = absolute_url(f"/nominee/{self.id}/")
        except Exception:
            nominee_url = None

        send_nominee_approved_email(
            to_email=self.contact_email,
            nominee_name=self.name,
            username=getattr(user, "username", None) or self.contact_email,
            temporary_password=temporary_password,
            account_created=account_created,
            categories=[self.category.name] if self.category else [],
            login_url=absolute_url("/accounts/login/"),
            dashboard_url=absolute_url("/association/dashboard/"),
            nominee_url=nominee_url,
            password_reset_url=absolute_url("/accounts/password-reset/"),
        )


    def send_approval_notice(self, user=None, temporary_password=None):
        """
        Create/connect the nominee's association account, set a real temporary
        password when needed, and send the polished approval email.

        Important:
        The password included in the email must match the password saved on the
        actual Django user account.
        """
        if not self.contact_email:
            return None

        email = self.contact_email.strip().lower()
        User = get_user_model()

        user = user or User.objects.filter(email__iexact=email).first() or User.objects.filter(username__iexact=email).first()

        created = False
        if user is None:
            temporary_password = temporary_password or secrets.token_urlsafe(10)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=temporary_password,
            )
            created = True
        else:
            if not user.email:
                user.email = email
                user.save(update_fields=["email"])

            # If caller supplies a temporary password, actually set it.
            # If no password was supplied, do not overwrite an existing user's password.
            if temporary_password:
                user.set_password(temporary_password)
                user.save(update_fields=["password"])

        membership, _created_membership = AssociationMembership.objects.get_or_create(
            user=user,
            nominee=self,
            defaults={"is_active": True},
        )

        if not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active", "activated_at"])

        # If the user was newly created, temporary_password is guaranteed.
        # If this is an existing user and no temporary_password was supplied,
        # the email will not show a fake password.
        self.send_approval_email(
            user,
            temporary_password=temporary_password if (created or temporary_password) else None,
            account_created=created,
        )

        return user

    def archive(self):
        self.is_active = False
        if not self.deleted_at:
            self.deleted_at = timezone.now()
        self.save(update_fields=["is_active", "deleted_at", "updated_at"])


# ---------------------------------------------------------------------
# Nomination Ledger
# ---------------------------------------------------------------------

class CommunicationPreference(models.Model):
    """
    Current email-level preference for optional ATL's Hottest promotional
    communications.

    Historical consent evidence remains on the original nomination/check-in
    records. Transactional and service communications are not controlled by
    this preference.
    """

    email = models.EmailField(unique=True, db_index=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="communication_preference",
        blank=True,
        null=True,
    )

    marketing_allowed = models.BooleanField(default=False)

    consented_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When promotional communications were most recently authorized.",
    )

    consent_version = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Consent-language version associated with the current authorization.",
    )

    withdrawn_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When promotional communications were most recently withdrawn.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email"]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def grant_marketing_consent(self, *, version="2026-09-v1"):
        self.marketing_allowed = True
        self.consented_at = timezone.now()
        self.consent_version = version
        self.withdrawn_at = None
        self.save()

    def withdraw_marketing_consent(self):
        self.marketing_allowed = False
        self.withdrawn_at = timezone.now()

        # Preserve consented_at and consent_version as historical evidence.
        self.save()

    def __str__(self):
        status = "allowed" if self.marketing_allowed else "withdrawn"
        return f"{self.email} ({status})"


class NominationLedger(models.Model):
    """
    Permanent record of each valid ATL's Hottest nomination recognition.

    The public Nominee record remains the canonical nominee/category record.
    This ledger preserves who submitted each nomination so multiple fans can
    nominate the same person while preventing one email address from counting
    more than once for the same nominee/category.
    """

    campaign = models.ForeignKey(
        "VotingCampaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(class)s_records",
        help_text="Awards cycle associated with this record.",
    )
    nominee = models.ForeignKey(
        Nominee,
        on_delete=models.PROTECT,
        related_name="nomination_records",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="nomination_records",
    )

    nominator_name = models.CharField(max_length=160)
    nominator_email = models.EmailField()

    submitted_nominee_name = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Preserves the nominee name exactly as submitted by the fan.",
    )

    communications_consent = models.BooleanField(
        default=False,
        help_text=(
            "Optional consent to receive ATL's Hottest Awards news, "
            "announcements, invitations, promotions, and marketing communications."
        ),
    )

    communications_consent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When optional promotional communications consent was recorded.",
    )

    communications_consent_version = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Version of the communications consent language accepted.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "nominator_email", "nominee", "category"],
                name="one_nomination_per_campaign_email_nominee_category",
            ),
        ]
        indexes = [
            models.Index(fields=["nominee", "category"]),
            models.Index(fields=["nominator_email"]),
            models.Index(fields=["created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.nominator_email:
            self.nominator_email = self.nominator_email.strip().lower()

        if not self.submitted_nominee_name and self.nominee_id:
            self.submitted_nominee_name = self.nominee.name

        # Optional promotional communications consent audit trail.
        #
        # Transactional/service communications such as nomination status,
        # account security, password resets, receipts, and other messages
        # necessary to provide the service are NOT controlled by this flag.
        if self.communications_consent:
            if not self.communications_consent_at:
                self.communications_consent_at = timezone.now()

            if not self.communications_consent_version:
                self.communications_consent_version = "2026-09-v1"
        else:
            self.communications_consent_at = None
            self.communications_consent_version = ""

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.nominator_name} nominated "
            f"{self.submitted_nominee_name or self.nominee.name} "
            f"for {self.category.name}"
        )


# ---------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------

class VoteQuerySet(models.QuerySet):
    def tallies(self):
        return (
            self.values(
                "category__slug",
                "category__name",
                "nominee__id",
                "nominee__name",
            )
            .annotate(count=Count("id"))
            .order_by("category__name", "-count", "nominee__name")
        )


class Vote(models.Model):
    campaign = models.ForeignKey(
        "VotingCampaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(class)s_records",
        help_text="Awards cycle associated with this record.",
    )
    email = models.EmailField()
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="votes")
    nominee = models.ForeignKey(Nominee, on_delete=models.CASCADE, related_name="votes")

    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    objects = VoteQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "email", "category"],
                name="one_vote_per_email_per_campaign_category",
            ),
        ]
        indexes = [
            models.Index(fields=["email", "category"]),
            models.Index(fields=["category", "nominee"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.nominee.name} ({self.category.name})"


# ---------------------------------------------------------------------
# Association / nominee management
# ---------------------------------------------------------------------


class AssociationProfile(models.Model):
    LEVEL_SILVER = "silver"
    LEVEL_GOLD = "gold"
    LEVEL_PLATINUM = "platinum"

    LEVEL_CHOICES = (
        (LEVEL_SILVER, "Silver"),
        (LEVEL_GOLD, "Gold"),
        (LEVEL_PLATINUM, "Platinum"),
    )

    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="association_profile")
    full_name = models.CharField(max_length=160, blank=True)
    business_name = models.CharField(max_length=180, blank=True)
    social_media = models.URLField(blank=True, null=True)
    website = models.URLField(blank=True)
    notification_email = models.EmailField(blank=True)
    profile_pic = models.ImageField(
        upload_to="association_profiles/",
        blank=True,
        null=True,
        validators=[validate_safe_image_upload],
    )
    special_interest = models.TextField(
        blank=True,
        help_text="Tell us what you are most interested in: entertainment, events, media, business, venues, creative work, sponsorship, community, etc.",
    )
    member_level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_SILVER)
    member_since = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user__username",)

    def __str__(self):
        return self.full_name or self.user.get_username()


class AssociationMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="association_memberships",
    )
    nominee = models.ForeignKey(
        Nominee,
        on_delete=models.CASCADE,
        related_name="association_memberships",
    )
    is_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["nominee__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "nominee"],
                name="unique_user_nominee_membership",
            ),
        ]

    def __str__(self) -> str:
        status = "active" if self.is_active else "pending"
        return f"{self.user} manages {self.nominee} ({status})"

    def save(self, *args, **kwargs):
        if self.is_active and not self.activated_at:
            self.activated_at = timezone.now()
        super().save(*args, **kwargs)


class NominationCategoryRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="category_requests",
    )
    source_nominee = models.ForeignKey(
        Nominee,
        on_delete=models.CASCADE,
        related_name="category_requests",
    )
    target_category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="nomination_requests",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["requester", "source_nominee", "target_category"],
                name="unique_category_request_per_nominee",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_nominee.name} → {self.target_category.name} ({self.status})"


# =========================================================
# ATL's Hottest Advertising Campaign Engine
# Powered By The MajesticMall Megaverse Advertising Platform
# =========================================================

class AdvertisingCampaign(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending Approval"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    advertiser_name = models.CharField(max_length=180)
    campaign_name = models.CharField(max_length=180)
    contact_name = models.CharField(max_length=140, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)

    total_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total budget shared across all billboard properties in this campaign.",
    )

    minimum_campaign_spend = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Minimum total spend required for this campaign.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )

    starts_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)

    internal_notes = models.TextField(blank=True)

    advertiser_report_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    advertiser_report_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Controls whether the secure advertiser delivery "
            "report is currently accessible."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Advertising Campaign"
        verbose_name_plural = "Advertising Campaigns"

    def __str__(self):
        return f"{self.campaign_name} — {self.advertiser_name}"

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}

        if (
            self.starts_at
            and self.ends_at
            and self.ends_at <= self.starts_at
        ):
            errors["ends_at"] = (
                "Campaign end time must be after the start time."
            )

        if self.total_budget is not None and self.total_budget < 0:
            errors["total_budget"] = (
                "Campaign budget cannot be negative."
            )

        if (
            self.minimum_campaign_spend is not None
            and self.minimum_campaign_spend < 0
        ):
            errors["minimum_campaign_spend"] = (
                "Minimum campaign spend cannot be negative."
            )

        # Do not allow a campaign to become active if its
        # booked inventory exceeds its budget or minimum rules.
        if self.pk and self.status == self.STATUS_ACTIVE:
            if not self.budget_is_valid:
                errors["status"] = (
                    "This campaign cannot be activated until its "
                    "budget and minimum-spend requirements are valid."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def allocated_total(self):
        from django.db.models import Sum
        total = self.billboard_ads.aggregate(
            total=Sum("allocated_budget")
        )["total"]
        return total or 0

    @property
    def remaining_budget(self):
        return self.total_budget - self.allocated_total

    @property
    def selected_property_count(self):
        return self.billboard_ads.count()

    @property
    def required_minimum_spend(self):
        from decimal import Decimal

        minimums = [
            ad.minimum_spend or Decimal("0")
            for ad in self.billboard_ads.all()
        ]

        property_minimum = max(minimums, default=Decimal("0"))

        # Multi-property campaigns require at least $50 total spend.
        multi_property_minimum = (
            Decimal("50.00")
            if self.selected_property_count > 1
            else Decimal("0")
        )

        return max(
            self.minimum_campaign_spend or Decimal("0"),
            property_minimum,
            multi_property_minimum,
        )

    @property
    def budget_is_valid(self):
        return (
            self.total_budget >= self.required_minimum_spend
            and self.allocated_total <= self.total_budget
        )


# =========================================================
# ATL's Hottest Billboard System
# Powered By The MajesticMall Megaverse Advertising Platform
# =========================================================

class BillboardAd(models.Model):
    PLACEMENT_SITEWIDE = "sitewide"
    PLACEMENT_HOMEPAGE_TOP = "homepage_top"
    PLACEMENT_HOMEPAGE_VIDEO = "homepage_video"
    PLACEMENT_VOTING_TOP = "voting_top"
    PLACEMENT_CATEGORY_TOP = "category_top"
    PLACEMENT_NOMINEE_PROFILE = "nominee_profile"
    PLACEMENT_EVENTS_TOP = "events_top"
    PLACEMENT_MARKETPLACE_TOP = "marketplace_top"
    PLACEMENT_MEMBERSHIP_TOP = "membership_top"
    PLACEMENT_ADVERTISING_TOP = "advertising_top"
    PLACEMENT_CONFIRMATION = "confirmation"
    PLACEMENT_ATL_TV = "atl_tv"

    PLACEMENT_CHOICES = [
        (PLACEMENT_SITEWIDE, "ATL's Hottest Sitewide Billboard"),
        (PLACEMENT_HOMEPAGE_TOP, "Homepage Red Carpet Billboard"),
        (PLACEMENT_HOMEPAGE_VIDEO, "Homepage TV Sponsor Billboard"),
        (PLACEMENT_VOTING_TOP, "Voting Page Billboard"),
        (PLACEMENT_CATEGORY_TOP, "Category Sponsor Billboard"),
        (PLACEMENT_NOMINEE_PROFILE, "Nominee Profile Sponsor"),
        (PLACEMENT_EVENTS_TOP, "What's Happening In The ATL Billboard"),
        (PLACEMENT_MARKETPLACE_TOP, "ATL's Hottest Marketplace Billboard"),
        (PLACEMENT_MEMBERSHIP_TOP, "Membership Billboard"),
        (PLACEMENT_ADVERTISING_TOP, "Advertising Command Center Billboard"),
        (PLACEMENT_CONFIRMATION, "Confirmation Page Billboard"),
        (PLACEMENT_ATL_TV, "ATL TV Sponsor Billboard"),
    ]

    PURCHASE_ROTATION = "rotation"
    PURCHASE_EXCLUSIVE = "exclusive"

    PURCHASE_TYPE_CHOICES = [
        (PURCHASE_ROTATION, "Rotating Billboard Slot"),
        (PURCHASE_EXCLUSIVE, "Exclusive Whole Billboard"),
    ]

    campaign = models.ForeignKey(
        "AdvertisingCampaign",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="billboard_ads",
        help_text="Optional campaign that owns the shared budget for this billboard booking.",
    )

    advertiser_name = models.CharField(max_length=160)
    title = models.CharField(max_length=180)
    subtitle = models.CharField(max_length=240, blank=True)
    placement = models.CharField(
        max_length=40,
        choices=PLACEMENT_CHOICES,
        default=PLACEMENT_HOMEPAGE_TOP,
    )

    purchase_type = models.CharField(
        max_length=20,
        choices=PURCHASE_TYPE_CHOICES,
        default=PURCHASE_ROTATION,
        help_text="Rotating slots share this property. Exclusive purchases take over the whole billboard while active.",
    )
    campaign_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Advertiser's total campaign budget across all selected properties.",
    )
    allocated_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Amount of the campaign budget allocated to this billboard property.",
    )
    minimum_spend = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Minimum spend required for this billboard property.",
    )
    is_premium_property = models.BooleanField(
        default=False,
        help_text="Marks premium inventory such as major homepage billboard properties.",
    )
    rotation_weight = models.PositiveIntegerField(
        default=1,
        help_text="Relative rotation frequency. 1 = standard; higher values receive proportionally more appearances.",
    )

    image = models.ImageField(
        upload_to="billboards/",
        blank=True,
        null=True,
        validators=[validate_safe_image_upload],
    )
    destination_url = models.URLField(blank=True)
    call_to_action = models.CharField(max_length=80, default="Learn More")
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    priority = models.PositiveIntegerField(default=100)
    impressions_note = models.CharField(
        max_length=180,
        blank=True,
        help_text="Optional internal note, such as package name or sponsor slot."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "-created_at"]
        verbose_name = "Billboard Ad"
        verbose_name_plural = "Billboard Ads"

    def __str__(self):
        return f"{self.title} — {self.get_placement_display()}"

    def clean(self):
        from decimal import Decimal

        from django.core.exceptions import ValidationError
        from django.db.models import Q, Sum

        errors = {}

        allocated = self.allocated_budget or Decimal("0")
        minimum = self.minimum_spend or Decimal("0")

        if allocated < 0:
            errors["allocated_budget"] = (
                "Allocated budget cannot be negative."
            )

        if minimum < 0:
            errors["minimum_spend"] = (
                "Minimum spend cannot be negative."
            )

        if self.rotation_weight < 1:
            errors["rotation_weight"] = (
                "Rotation weight must be at least 1."
            )

        if (
            self.starts_at
            and self.ends_at
            and self.ends_at <= self.starts_at
        ):
            errors["ends_at"] = (
                "Billboard end time must be after the start time."
            )

        if self.is_active and allocated < minimum:
            errors["allocated_budget"] = (
                f"This billboard requires a minimum allocation "
                f"of ${minimum:.2f} before it can be active."
            )

        if self.campaign_id:
            campaign = self.campaign

            if (
                campaign.starts_at
                and self.starts_at
                and self.starts_at < campaign.starts_at
            ):
                errors["starts_at"] = (
                    "Billboard cannot start before its campaign."
                )

            if (
                campaign.ends_at
                and self.ends_at
                and self.ends_at > campaign.ends_at
            ):
                errors["ends_at"] = (
                    "Billboard cannot end after its campaign."
                )

            other_allocated = (
                campaign.billboard_ads
                .exclude(pk=self.pk)
                .aggregate(total=Sum("allocated_budget"))["total"]
                or Decimal("0")
            )

            if other_allocated + allocated > campaign.total_budget:
                available = campaign.total_budget - other_allocated

                errors["allocated_budget"] = (
                    f"This allocation exceeds the campaign budget. "
                    f"Maximum available for this property is "
                    f"${available:.2f}."
                )

        # Exclusive inventory cannot overlap another active
        # exclusive booking for the same billboard property.
        if (
            self.is_active
            and self.purchase_type == self.PURCHASE_EXCLUSIVE
        ):
            overlapping = BillboardAd.objects.filter(
                placement=self.placement,
                purchase_type=self.PURCHASE_EXCLUSIVE,
                is_active=True,
            ).exclude(pk=self.pk)

            if self.starts_at:
                overlapping = overlapping.filter(
                    Q(ends_at__isnull=True)
                    | Q(ends_at__gt=self.starts_at)
                )

            if self.ends_at:
                overlapping = overlapping.filter(
                    Q(starts_at__isnull=True)
                    | Q(starts_at__lt=self.ends_at)
                )

            if overlapping.exists():
                errors["purchase_type"] = (
                    "Another exclusive booking overlaps this "
                    "billboard property during the selected schedule."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def is_current(self):
        from django.utils import timezone
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True


# =========================================================
# ATL's Hottest Advertise Command Center
# Powered By The MajesticMall Megaverse Advertising Platform
# =========================================================

class BillboardAdEvent(models.Model):
    EVENT_IMPRESSION = "impression"
    EVENT_CLICK = "click"

    EVENT_CHOICES = [
        (EVENT_IMPRESSION, "Impression"),
        (EVENT_CLICK, "Click"),
    ]

    ad = models.ForeignKey(
        "BillboardAd",
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_CHOICES,
    )
    placement = models.CharField(
        max_length=40,
        blank=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["ad", "event_type", "created_at"],
            ),
        ]
        verbose_name = "Billboard Ad Event"
        verbose_name_plural = "Billboard Ad Events"

    def __str__(self):
        return (
            f"{self.ad.title} — "
            f"{self.get_event_type_display()}"
        )


class AdvertisingInquiry(models.Model):
    PLACEMENT_SITEWIDE = "sitewide"
    PLACEMENT_HOMEPAGE = "homepage_top"
    PLACEMENT_HOMEPAGE_VIDEO = "homepage_video"
    PLACEMENT_VOTING = "voting_top"
    PLACEMENT_CATEGORY = "category_top"
    PLACEMENT_NOMINEE = "nominee_profile"
    PLACEMENT_EVENTS = "events_top"
    PLACEMENT_MARKETPLACE = "marketplace_top"
    PLACEMENT_MEMBERSHIP = "membership_top"
    PLACEMENT_ADVERTISING = "advertising_top"
    PLACEMENT_ATL_TV = "atl_tv"
    PLACEMENT_CONFIRMATION = "confirmation"
    PLACEMENT_FULL_CAMPAIGN = "full_campaign"

    PLACEMENT_CHOICES = [
        (PLACEMENT_SITEWIDE, "ATL's Hottest Sitewide Billboard"),
        (PLACEMENT_HOMEPAGE, "Homepage Red Carpet Billboard"),
        (PLACEMENT_HOMEPAGE_VIDEO, "Homepage TV Sponsor Billboard"),
        (PLACEMENT_VOTING, "Voting Page Billboard"),
        (PLACEMENT_CATEGORY, "Category Sponsor Billboard"),
        (PLACEMENT_NOMINEE, "Nominee Profile Sponsor"),
        (PLACEMENT_EVENTS, "What's Happening In The ATL Billboard"),
        (PLACEMENT_MARKETPLACE, "ATL's Hottest Marketplace Billboard"),
        (PLACEMENT_MEMBERSHIP, "Membership Billboard"),
        (PLACEMENT_ADVERTISING, "Advertising Command Center Billboard"),
        (PLACEMENT_ATL_TV, "ATL TV Sponsor Billboard"),
        (PLACEMENT_CONFIRMATION, "Confirmation Page Billboard"),
        (PLACEMENT_FULL_CAMPAIGN, "Full ATL’s Hottest Campaign"),
    ]

    PURCHASE_ROTATION = "rotation"
    PURCHASE_EXCLUSIVE = "exclusive"

    PURCHASE_TYPE_CHOICES = [
        (PURCHASE_ROTATION, "Rotating Billboard Slot"),
        (PURCHASE_EXCLUSIVE, "Exclusive Whole Billboard"),
    ]

    business_name = models.CharField(max_length=180)
    contact_name = models.CharField(max_length=140)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)
    placement_interest = models.CharField(
        max_length=40,
        choices=PLACEMENT_CHOICES,
        default=PLACEMENT_HOMEPAGE,
    )
    budget_range = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional budget notes or campaign spend details."
    )
    total_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total campaign budget shared across selected advertising properties.",
    )
    purchase_type = models.CharField(
        max_length=20,
        choices=PURCHASE_TYPE_CHOICES,
        default=PURCHASE_ROTATION,
        help_text="Choose shared rotating inventory or request the entire billboard exclusively.",
    )
    requested_placements = models.JSONField(
        default=list,
        blank=True,
        help_text="Advertising property keys requested for this campaign.",
    )
    requested_start_date = models.DateField(blank=True, null=True)
    requested_end_date = models.DateField(blank=True, null=True)
    creative_upload = models.FileField(
        upload_to="advertising_inquiries/",
        blank=True,
        null=True,
        validators=[validate_safe_image_upload],
        help_text="Optional JPG, PNG, or WEBP ad creative, flyer, logo, or campaign artwork. Maximum 10 MB."
    )
    creative_notes = models.TextField(
        blank=True,
        help_text="Optional notes about ad creative, sizing, copy, links, or campaign instructions."
    )
    campaign_message = models.TextField(
        blank=True,
        help_text="What does the advertiser want to promote?"
    )
    is_contacted = models.BooleanField(default=False)
    internal_notes = models.TextField(blank=True)

    converted_campaign = models.ForeignKey(
        "AdvertisingCampaign",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="source_inquiries",
        help_text="Campaign created from this advertising inquiry.",
    )
    converted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    last_activity_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Most recent meaningful sales/workflow activity for this "
            "advertising inquiry."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    ACTIVITY_TRACKED_FIELDS = {
        "is_contacted",
        "internal_notes",
        "converted_campaign_id",
        "converted_at",
        "requested_start_date",
        "requested_end_date",
        "requested_placements",
        "total_budget",
        "purchase_type",
        "placement_interest",
        "creative_upload",
        "creative_notes",
        "campaign_message",
    }

    def save(self, *args, **kwargs):
        """
        Maintain last_activity_at only for meaningful inquiry workflow activity.

        New inquiries receive an initial activity timestamp.

        Existing historical rows whose last_activity_at is NULL are NOT
        backfilled merely because Django saves them. Their timestamp changes
        only when a tracked workflow field actually changes.
        """
        from django.utils import timezone

        now = timezone.now()

        if self._state.adding:
            if self.last_activity_at is None:
                self.last_activity_at = now

        elif self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()

            if previous is not None:
                changed = False

                for field_name in self.ACTIVITY_TRACKED_FIELDS:
                    if getattr(previous, field_name) != getattr(
                        self, field_name
                    ):
                        changed = True
                        break

                if changed:
                    self.last_activity_at = now

        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            update_fields = set(update_fields)

            if (
                self._state.adding
                or self.last_activity_at is not None
            ):
                update_fields.add("last_activity_at")

            kwargs["update_fields"] = list(update_fields)

        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Advertising Inquiry"
        verbose_name_plural = "Advertising Inquiries"

    def __str__(self):
        return f"{self.business_name} — {self.get_placement_interest_display()}"



# =========================================================
# ATL'S HOTTEST AUTOPILOT MEMBERSHIP ENGINE
# =========================================================

class MembershipPlan(models.Model):
    BILLING_CHOICES = [
        ("free", "Free"),
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
        ("one_time", "One-Time"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    tagline = models.CharField(max_length=180, blank=True)
    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    billing_period = models.CharField(max_length=20, choices=BILLING_CHOICES, default="monthly")

    badge_label = models.CharField(max_length=80, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    external_checkout_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "price", "name"]

    def __str__(self):
        return self.name

    @property
    def is_free(self):
        return self.price == 0


class MembershipBenefit(models.Model):
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE, related_name="benefits")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=40, blank=True, help_text="Optional emoji or short icon text.")
    display_order = models.PositiveIntegerField(default=0)
    is_highlighted = models.BooleanField(default=False)

    class Meta:
        ordering = ["display_order", "title"]

    def __str__(self):
        return f"{self.plan.name} — {self.title}"


class MembershipReward(models.Model):
    REWARD_TYPES = [
        ("visibility", "Visibility"),
        ("discount", "Discount"),
        ("credit", "Credit"),
        ("badge", "Badge"),
        ("access", "Access"),
        ("other", "Other"),
    ]

    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE, related_name="rewards")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    reward_type = models.CharField(max_length=30, choices=REWARD_TYPES, default="other")
    value = models.CharField(max_length=120, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "title"]

    def __str__(self):
        return f"{self.plan.name} — {self.title}"


class UserMembership(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("past_due", "Past Due"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="atl_membership",
    )
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="members")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")

    started_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    auto_renew = models.BooleanField(default=False)

    payment_reference = models.CharField(max_length=180, blank=True)
    internal_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user} — {self.plan.name} ({self.status})"


# =========================================================
# ATL'S HOTTEST VOTING CAMPAIGN CONTROL
# Allows admin/white-label organizations to open and close voting.
# =========================================================

class VotingCampaign(models.Model):
    name = models.CharField(max_length=160, default="ATL's Hottest Awards Campaign")
    slug = models.SlugField(unique=True, default="atl-hottest-awards")

    nominations_enabled = models.BooleanField(
        default=True,
        help_text="Allow nominees to be submitted during the nomination period."
    )

    voting_enabled = models.BooleanField(
        default=False,
        help_text="Manual master switch. Admin can turn voting on/off instantly."
    )

    campaign_start_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Voting opens on this date/time if voting is enabled."
    )

    campaign_end_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Voting closes after this date/time."
    )

    is_active_campaign = models.BooleanField(
        default=True,
        help_text="Only one campaign should normally be active at a time."
    )

    public_message = models.CharField(
        max_length=220,
        blank=True,
        default="Voting is not open yet. Nominations may still be active."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active_campaign", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active_campaign"],
                condition=models.Q(is_active_campaign=True),
                name="one_active_voting_campaign",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_voting_open(self):
        now = timezone.now()

        if not self.is_active_campaign:
            return False

        if not self.voting_enabled:
            return False

        if self.campaign_start_date and now < self.campaign_start_date:
            return False

        if self.campaign_end_date and now > self.campaign_end_date:
            return False

        return True

    @property
    def voting_status_label(self):
        return "Voting Open" if self.is_voting_open else "Voting Closed"



class AtlsHottestEvent(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    CATEGORY_CHOICES = [
        ("events", "Events"),
        ("festivals", "Festivals"),
        ("nightlife", "Nightlife"),
        ("special_promotions", "Special Promotions"),
        ("whats_happening_today", "What's Happening Today"),
    ]

    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default="events")

    organizer_name = models.CharField(max_length=160)
    organizer_email = models.EmailField()
    organizer_phone = models.CharField(max_length=40, blank=True)

    venue_name = models.CharField(max_length=180, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, default="Atlanta")
    state = models.CharField(max_length=40, default="GA")

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)

    description = models.TextField()
    flyer = models.ImageField(
        upload_to="events/flyers/",
        blank=True,
        null=True,
        validators=[validate_safe_image_upload],
    )

    ticket_link = models.URLField(blank=True)
    website = models.URLField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    is_featured = models.BooleanField(default=False)
    show_today = models.BooleanField(default=False)

    # Premium homepage event promotion
    #
    # Event approval and homepage advertising are intentionally separate.
    # An approved event may appear in What's Happening In The ATL without
    # receiving premium homepage placement.
    show_on_homepage = models.BooleanField(
        default=False,
        help_text="Master switch for premium homepage event promotion.",
    )

    HOMEPAGE_PAYMENT_STATUS_CHOICES = [
        ("not_required", "Not Required"),
        ("unpaid", "Unpaid"),
        ("pending", "Payment Pending"),
        ("paid", "Paid"),
        ("comp", "Complimentary / Admin Comp"),
        ("refunded", "Refunded"),
    ]

    HOMEPAGE_PACKAGE_CHOICES = [
        ("", "No Homepage Promotion"),
        ("24_hours", "24 Hours"),
        ("3_days", "3 Days"),
        ("7_days", "7 Days"),
        ("custom", "Custom Campaign"),
    ]

    homepage_payment_status = models.CharField(
        max_length=20,
        choices=HOMEPAGE_PAYMENT_STATUS_CHOICES,
        default="not_required",
    )
    homepage_package = models.CharField(
        max_length=20,
        choices=HOMEPAGE_PACKAGE_CHOICES,
        blank=True,
        default="",
    )
    homepage_amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    homepage_promotion_start = models.DateTimeField(
        null=True,
        blank=True,
    )
    homepage_promotion_end = models.DateTimeField(
        null=True,
        blank=True,
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "title"]
        verbose_name = "ATL's Hottest Event"
        verbose_name_plural = "ATL's Hottest Events"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "atl-event"
            slug = base_slug
            counter = 2

            while AtlsHottestEvent.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)


class EventPromotionOrder(models.Model):
    """
    Producer-facing request/order for premium event promotion.

    This record is intentionally separate from AtlsHottestEvent so the
    event itself remains the permanent listing while promotion orders
    preserve campaign/payment history.
    """

    PACKAGE_CHOICES = [
        ("24_hours", "24 Hours"),
        ("3_days", "3 Days"),
        ("7_days", "7 Days"),
        ("custom", "Custom Campaign"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("awaiting_payment", "Awaiting Payment"),
        ("paid", "Paid"),
        ("activated", "Activated"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    event = models.ForeignKey(
        "AtlsHottestEvent",
        on_delete=models.CASCADE,
        related_name="promotion_orders",
    )

    producer_name = models.CharField(max_length=160)
    producer_email = models.EmailField()

    package = models.CharField(
        max_length=20,
        choices=PACKAGE_CHOICES,
    )

    requested_start = models.DateTimeField()
    requested_end = models.DateTimeField(
        null=True,
        blank=True,
    )

    quoted_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending",
    )

    notes = models.TextField(blank=True)

    is_complimentary = models.BooleanField(
        default=False,
        help_text="Staff-authorized complimentary promotion. Allows activation without a paid dollar amount.",
    )


    # Secure producer-facing payment identifier
    public_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    # Stripe payment tracking
    stripe_checkout_session_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
    )
    stripe_payment_status = models.CharField(
        max_length=50,
        blank=True,
    )
    paid_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.event.title} — {self.get_package_display()} — {self.get_status_display()}"


class EventPromotionRate(models.Model):
    """
    Admin-controlled pricing for ATL's Hottest premium event promotion.
    Prices live in the database so they can be changed without editing code.
    """

    PACKAGE_CHOICES = [
        ("24_hours", "24 Hours"),
        ("3_days", "3 Days"),
        ("7_days", "7 Days"),
        ("custom", "Custom Campaign"),
    ]

    package = models.CharField(
        max_length=20,
        choices=PACKAGE_CHOICES,
        unique=True,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    is_active = models.BooleanField(
        default=False,
        help_text="Only active packages can be purchased by producers.",
    )

    display_order = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_order", "amount")

    def __str__(self):
        return f"{self.get_package_display()} — ${self.amount}"


# ---------------------------------------------------------------------
# I AM ATL's Hottest Check-In
# ---------------------------------------------------------------------

class SelfNominationCheckIn(models.Model):
    """
    Public proclamation from a person checking in as ATL's Hottest.

    A Check-In is NOT an automatic nomination.
    Staff approval is required before official Nominee records are created.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending Review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
    )

    name = models.CharField(
        max_length=160,
        help_text="Name of the person proclaiming I AM ATL's Hottest.",
    )

    email = models.EmailField(
        help_text="Valid email address for Check-In and approval communication.",
    )

    website = models.URLField(
        blank=True,
        default="",
        help_text="Website used to help ATL's Hottest review this Check-In.",
    )

    social_link = models.URLField(
        blank=True,
        default="",
        help_text="Social media address used to help ATL's Hottest review this Check-In.",
    )

    categories = models.ManyToManyField(
        Category,
        related_name="self_nomination_checkins",
        help_text="Select from one to five ATL's Hottest categories.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    communications_consent = models.BooleanField(
        default=False,
        help_text=(
            "Optional consent to receive ATL's Hottest Awards news, "
            "announcements, invitations, promotions, and marketing "
            "communications."
        ),
    )

    communications_consent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When optional promotional communications consent was recorded.",
    )

    communications_consent_version = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Version of the communications consent language accepted.",
    )

    submitted_at = models.DateTimeField(auto_now_add=True)

    reviewed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    approved_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    denied_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    created_nominees = models.ManyToManyField(
        Nominee,
        blank=True,
        related_name="self_nomination_checkins",
        help_text=(
            "Official nominee records created only after this "
            "Check-In is approved."
        ),
    )

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "I AM ATL's Hottest Check-In"
        verbose_name_plural = "I AM ATL's Hottest Check-Ins"
        indexes = [
            models.Index(fields=["status", "submitted_at"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return f"{self.name} — {self.get_status_display()}"

    def clean(self):
        super().clean()

        if not self.website and not self.social_link:
            raise ValidationError(
                "Please provide at least one social media address or website "
                "so ATL's Hottest can review your Check-In."
            )

        if self.status == self.STATUS_APPROVED and self.denied_at:
            raise ValidationError(
                "An approved Check-In cannot also have a denied timestamp."
            )

    def mark_approved(self):
        now = timezone.now()
        self.status = self.STATUS_APPROVED
        self.reviewed_at = now
        self.approved_at = now
        self.denied_at = None
        self.save(
            update_fields=[
                "status",
                "reviewed_at",
                "approved_at",
                "denied_at",
            ]
        )

    def mark_denied(self):
        now = timezone.now()
        self.status = self.STATUS_DENIED
        self.reviewed_at = now
        self.denied_at = now
        self.approved_at = None
        self.save(
            update_fields=[
                "status",
                "reviewed_at",
                "denied_at",
                "approved_at",
            ]
        )



# =====================================================================
# 008-H — ATL'S HOTTEST SIX-SECOND ADVERTISING PLAYOUT ENGINE
# =====================================================================

class AdvertisingDaypart(models.Model):
    """
    Recurring pricing period for advertising inventory.

    Dayparts control pricing. They never change the atomic billboard
    inventory unit: one slot is always exactly six seconds.
    """

    name = models.CharField(max_length=100, unique=True)

    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
    )

    start_time = models.TimeField()
    end_time = models.TimeField()

    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "start_time", "name"]
        verbose_name = "Advertising Daypart"
        verbose_name_plural = "Advertising Dayparts"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "daypart"
            candidate = base_slug
            counter = 2

            while (
                AdvertisingDaypart.objects
                .filter(slug=candidate)
                .exclude(pk=self.pk)
                .exists()
            ):
                candidate = f"{base_slug}-{counter}"
                counter += 1

            self.slug = candidate[:120]

        super().save(*args, **kwargs)


class AdvertisingInventorySchedule(models.Model):
    """
    Weekly recurring price configuration for one advertising property,
    weekday and daypart.

    Six seconds is the permanent atomic inventory unit.

    Longer appearances consume consecutive six-second slots:
        6 sec  = 1 slot
        12 sec = 2 slots
        30 sec = 5 slots
        60 sec = 10 slots
    """

    SLOT_SECONDS = 6

    WEEKDAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    placement = models.CharField(
        max_length=50,
        choices=BillboardAd.PLACEMENT_CHOICES,
        db_index=True,
        help_text="Advertising property/display.",
    )

    weekday = models.PositiveSmallIntegerField(
        choices=WEEKDAY_CHOICES,
        db_index=True,
    )

    daypart = models.ForeignKey(
        AdvertisingDaypart,
        on_delete=models.PROTECT,
        related_name="inventory_schedules",
    )

    base_slot_price = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text="Base price for one six-second advertising slot.",
    )

    traffic_multiplier = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=1,
        help_text=(
            "Pricing multiplier for NEW inventory. "
            "1.0000 = base rate; 1.2500 = 25% increase."
        ),
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "placement",
            "weekday",
            "daypart__sort_order",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["placement", "weekday", "daypart"],
                name="unique_ad_inventory_property_day_daypart",
            ),
            models.CheckConstraint(
                condition=models.Q(base_slot_price__gte=0),
                name="ad_inventory_base_price_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(traffic_multiplier__gt=0),
                name="ad_inventory_traffic_multiplier_gt_zero",
            ),
        ]

        verbose_name = "Advertising Inventory Schedule"
        verbose_name_plural = "Advertising Inventory Schedules"

    def __str__(self):
        return (
            f"{self.get_placement_display()} — "
            f"{self.get_weekday_display()} — "
            f"{self.daypart.name}"
        )

    @classmethod
    def slots_per_minute(cls):
        return 60 // cls.SLOT_SECONDS

    @classmethod
    def slots_per_hour(cls):
        return cls.slots_per_minute() * 60

    @classmethod
    def slots_per_day(cls):
        return cls.slots_per_hour() * 24

    @classmethod
    def slots_per_week(cls):
        return cls.slots_per_day() * 7

    @classmethod
    def slots_required_for_duration(cls, duration_seconds):
        if duration_seconds <= 0:
            raise ValueError(
                "Creative duration must be greater than zero."
            )

        if duration_seconds % cls.SLOT_SECONDS:
            raise ValueError(
                "Creative duration must be a multiple of six seconds."
            )

        return duration_seconds // cls.SLOT_SECONDS

    @property
    def current_slot_price(self):
        """
        Price of one NEW six-second slot.

        Purchased inventory will later lock its sale price so future
        rate changes cannot rewrite historical purchases.
        """
        from decimal import Decimal, ROUND_HALF_UP

        amount = self.base_slot_price * self.traffic_multiplier

        return amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


class AdvertisingPlayoutCreative(models.Model):
    """
    Creative eligible for the 24/7 advertising playout engine.

    PAID:
        Purchased advertiser creative.

    HOUSE:
        ATL's Hottest promotional programming.

    ADVERTISE_HERE:
        Permanent fallback when no paid or eligible house creative
        occupies available inventory.
    """

    TYPE_PAID = "paid"
    TYPE_HOUSE = "house"
    TYPE_ADVERTISE_HERE = "advertise_here"

    CREATIVE_TYPE_CHOICES = [
        (TYPE_PAID, "Paid Advertiser"),
        (TYPE_HOUSE, "ATL's Hottest House Promotion"),
        (TYPE_ADVERTISE_HERE, "Advertise Here Fallback"),
    ]

    name = models.CharField(max_length=180)

    # ---------------------------------------------------------
    # 009-A2B — LIVE PRESENTATION BRIDGE
    #
    # The playout creative remains the scheduling object.
    # BillboardAd remains the advertiser-facing presentation
    # object containing artwork, CTA, destination and placement.
    # ---------------------------------------------------------
    billboard_ad = models.ForeignKey(
        "BillboardAd",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="playout_creatives",
        help_text=(
            "Optional billboard presentation rendered when this "
            "playout creative is delivered."
        ),
    )

    creative_type = models.CharField(
        max_length=30,
        choices=CREATIVE_TYPE_CHOICES,
        db_index=True,
    )

    duration_seconds = models.PositiveIntegerField(
        default=6,
        help_text=(
            "Creative duration. Must be a multiple of six seconds."
        ),
    )

    priority = models.PositiveIntegerField(
        default=0,
        help_text=(
            "House/fallback scheduling priority. "
            "Higher values receive greater priority."
        ),
    )

    starts_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    ends_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "name"]
        verbose_name = "Advertising Playout Creative"
        verbose_name_plural = "Advertising Playout Creatives"

    def __str__(self):
        return self.name

    @property
    def slots_required(self):
        return (
            AdvertisingInventorySchedule
            .slots_required_for_duration(
                self.duration_seconds
            )
        )

    def clean(self):
        super().clean()

        from django.core.exceptions import ValidationError

        if self.duration_seconds <= 0:
            raise ValidationError({
                "duration_seconds":
                    "Creative duration must be greater than zero."
            })

        if (
            self.duration_seconds %
            AdvertisingInventorySchedule.SLOT_SECONDS
        ):
            raise ValidationError({
                "duration_seconds":
                    "Creative duration must be a multiple of six seconds."
            })

        if (
            self.starts_at
            and self.ends_at
            and self.ends_at <= self.starts_at
        ):
            raise ValidationError({
                "ends_at":
                    "Ending time must be later than starting time."
            })

        # -----------------------------------------------------
        # 009-A2B — PRESENTATION CONTRACT
        # -----------------------------------------------------
        if self.billboard_ad_id:
            billboard = self.billboard_ad

            if (
                self.creative_type == self.TYPE_PAID
                and billboard.campaign_id is None
            ):
                raise ValidationError({
                    "billboard_ad": (
                        "Paid playout creatives must use a billboard "
                        "presentation owned by an advertising campaign."
                    )
                })


# =====================================================================
# 008-H2 — SIX-SECOND PLAYOUT RESERVATION LEDGER
# =====================================================================

class AdvertisingPlayoutReservation(models.Model):
    """
    One row represents ownership of exactly ONE six-second inventory unit.

    Longer appearances use multiple consecutive rows that share the same
    appearance_id.

    Example:
        12-second appearance = 2 consecutive rows
        30-second appearance = 5 consecutive rows
        60-second appearance = 10 consecutive rows

    Database uniqueness prevents two reservations from owning the same
    advertising property at the same six-second start timestamp.
    """

    STATUS_RESERVED = "reserved"
    STATUS_PLAYED = "played"
    STATUS_CANCELLED = "cancelled"
    STATUS_MISSED = "missed"

    STATUS_CHOICES = [
        (STATUS_RESERVED, "Reserved"),
        (STATUS_PLAYED, "Played"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_MISSED, "Missed"),
    ]

    SOURCE_PAID = "paid"
    SOURCE_HOUSE = "house"
    SOURCE_ADVERTISE_HERE = "advertise_here"

    SOURCE_CHOICES = [
        (SOURCE_PAID, "Paid Advertiser"),
        (SOURCE_HOUSE, "ATL's Hottest House Promotion"),
        (SOURCE_ADVERTISE_HERE, "Advertise Here Fallback"),
    ]

    appearance_id = models.UUIDField(
        default=uuid.uuid4,
        db_index=True,
        help_text=(
            "All six-second units belonging to one uninterrupted "
            "appearance share this identifier."
        ),
    )

    placement = models.CharField(
        max_length=50,
        choices=BillboardAd.PLACEMENT_CHOICES,
        db_index=True,
    )

    creative = models.ForeignKey(
        AdvertisingPlayoutCreative,
        on_delete=models.PROTECT,
        related_name="playout_reservations",
    )

    campaign = models.ForeignKey(
        "AdvertisingCampaign",
        on_delete=models.PROTECT,
        related_name="playout_reservations",
        null=True,
        blank=True,
        help_text=(
            "Paid advertising campaign that purchased this six-second "
            "inventory unit. House and Advertise Here inventory may be blank."
        ),
    )

    source_type = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        db_index=True,
    )

    slot_start = models.DateTimeField(
        db_index=True,
        help_text="Start of this exact six-second inventory unit.",
    )

    slot_end = models.DateTimeField(
        help_text="End of this exact six-second inventory unit.",
    )

    sequence_number = models.PositiveIntegerField(
        default=1,
        help_text=(
            "Position of this slot inside the complete appearance. "
            "A 12-second appearance uses sequence numbers 1 and 2."
        ),
    )

    appearance_slot_count = models.PositiveIntegerField(
        default=1,
        help_text=(
            "Total six-second units required by the complete appearance."
        ),
    )

    locked_slot_price = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text=(
            "Sale price permanently locked for this six-second unit. "
            "Future rate changes do not alter this value."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RESERVED,
        db_index=True,
    )

    played_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Actual proof-of-play timestamp.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "placement",
            "slot_start",
            "sequence_number",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["placement", "slot_start"],
                name="unique_ad_playout_property_slot",
            ),
            models.UniqueConstraint(
                fields=["appearance_id", "sequence_number"],
                name="unique_ad_playout_appearance_sequence",
            ),
            models.CheckConstraint(
                condition=models.Q(locked_slot_price__gte=0),
                name="ad_playout_locked_price_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_number__gte=1),
                name="ad_playout_sequence_gte_one",
            ),
            models.CheckConstraint(
                condition=models.Q(appearance_slot_count__gte=1),
                name="ad_playout_slot_count_gte_one",
            ),
        ]

        verbose_name = "Advertising Playout Reservation"
        verbose_name_plural = "Advertising Playout Reservations"

    def __str__(self):
        return (
            f"{self.get_placement_display()} — "
            f"{self.slot_start} — "
            f"{self.sequence_number}/{self.appearance_slot_count}"
        )

    def clean(self):
        super().clean()

        from datetime import timedelta
        from django.core.exceptions import ValidationError

        expected_end = self.slot_start + timedelta(
            seconds=AdvertisingInventorySchedule.SLOT_SECONDS
        )

        if self.slot_end != expected_end:
            raise ValidationError({
                "slot_end": (
                    "Every reservation row must represent exactly "
                    "one six-second inventory unit."
                )
            })

        if self.sequence_number > self.appearance_slot_count:
            raise ValidationError({
                "sequence_number": (
                    "Sequence number cannot exceed the appearance "
                    "slot count."
                )
            })

        expected_slots = (
            AdvertisingInventorySchedule
            .slots_required_for_duration(
                self.creative.duration_seconds
            )
        )

        if self.appearance_slot_count != expected_slots:
            raise ValidationError({
                "appearance_slot_count": (
                    "Appearance slot count must match the creative's "
                    "six-second duration."
                )
            })

        if self.source_type != self.creative.creative_type:
            raise ValidationError({
                "source_type": (
                    "Reservation source type must match the creative type."
                )
            })

        if (
            self.source_type == self.SOURCE_PAID
            and self.campaign_id is None
        ):
            raise ValidationError({
                "campaign": (
                    "Paid advertising inventory must belong to an "
                    "Advertising Campaign."
                )
            })


def reserve_advertising_appearance(
    *,
    placement,
    creative,
    starts_at,
    locked_slot_price,
    campaign=None,
):
    """
    Atomically reserve one complete uninterrupted appearance.

    Either every required six-second slot is reserved or none are.

    The database uniqueness constraint provides the final collision
    protection if another process attempts to reserve the same inventory.
    """

    from datetime import timedelta
    from decimal import Decimal

    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction

    slot_count = (
        AdvertisingInventorySchedule
        .slots_required_for_duration(
            creative.duration_seconds
        )
    )

    if locked_slot_price < Decimal("0"):
        raise ValidationError(
            "Locked slot price cannot be negative."
        )

    appearance_id = uuid.uuid4()
    reservations = []

    try:
        with transaction.atomic():
            for index in range(slot_count):
                slot_start = starts_at + timedelta(
                    seconds=(
                        index *
                        AdvertisingInventorySchedule.SLOT_SECONDS
                    )
                )

                slot_end = slot_start + timedelta(
                    seconds=AdvertisingInventorySchedule.SLOT_SECONDS
                )

                reservation = AdvertisingPlayoutReservation(
                    appearance_id=appearance_id,
                    placement=placement,
                    creative=creative,
                    campaign=campaign,
                    source_type=creative.creative_type,
                    slot_start=slot_start,
                    slot_end=slot_end,
                    sequence_number=index + 1,
                    appearance_slot_count=slot_count,
                    locked_slot_price=locked_slot_price,
                )

                reservation.full_clean()
                reservation.save()

                reservations.append(reservation)

    except IntegrityError as exc:
        raise ValidationError(
            "One or more requested six-second slots are already reserved."
        ) from exc

    return reservations


# =====================================================================
# 008-H3A — CAMPAIGN PLAYOUT MONEY LEDGER
# =====================================================================

class AdvertisingRevenuePolicy(models.Model):
    """
    Configurable internal accounting policy for advertising media spend.

    IMPORTANT:
    The advertiser receives the full media value purchased.

    Example:
        Advertiser media spend:        $100.00
        ATL's Hottest revenue share:    $15.00 at 15%
        Media value delivered:         $100.00

    The revenue share is an internal allocation of collected advertising
    revenue. It does NOT reduce the advertiser's purchased media value.
    """

    name = models.CharField(
        max_length=120,
        default="ATL's Hottest Standard Advertising Revenue Policy",
    )

    platform_share_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("15.000"),
        help_text=(
            "ATL's Hottest internal share of advertising media spend. "
            "15.000 means 15 percent."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    effective_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_at", "-id"]
        verbose_name = "Advertising Revenue Policy"
        verbose_name_plural = "Advertising Revenue Policies"

    def __str__(self):
        return (
            f"{self.name} — "
            f"{self.platform_share_percent}%"
        )

    def clean(self):
        super().clean()

        if self.platform_share_percent < 0:
            raise ValidationError({
                "platform_share_percent":
                    "Platform revenue share cannot be negative."
            })

        if self.platform_share_percent > 100:
            raise ValidationError({
                "platform_share_percent":
                    "Platform revenue share cannot exceed 100 percent."
            })

    @classmethod
    def current(cls):
        return (
            cls.objects
            .filter(
                is_active=True,
                effective_at__lte=timezone.now(),
            )
            .order_by("-effective_at", "-id")
            .first()
        )


class AdvertisingCampaignSpend(models.Model):
    """
    Immutable financial snapshot for one purchased advertising appearance.

    One spend row represents ONE complete appearance, even when that
    appearance contains multiple consecutive six-second reservations.

    Example:
        12-second creative
        2 x six-second reservations
        $0.75 per six-second unit

        media_spend          = $1.50
        platform_share_rate  = 15.000%
        platform_share       = $0.23

    The campaign consumes $1.50 of advertiser media budget — NOT $1.73.
    """

    campaign = models.ForeignKey(
        "AdvertisingCampaign",
        on_delete=models.PROTECT,
        related_name="playout_spend_entries",
    )

    creative = models.ForeignKey(
        "AdvertisingPlayoutCreative",
        on_delete=models.PROTECT,
        related_name="campaign_spend_entries",
    )

    appearance_id = models.UUIDField(
        unique=True,
        db_index=True,
        help_text=(
            "Appearance identifier shared by all six-second reservation "
            "rows represented by this spend entry."
        ),
    )

    placement = models.CharField(
        max_length=50,
        choices=BillboardAd.PLACEMENT_CHOICES,
        db_index=True,
    )

    slot_count = models.PositiveIntegerField(
        help_text="Number of six-second units purchased.",
    )

    locked_slot_price = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text=(
            "Locked sale price of one six-second unit at purchase time."
        ),
    )

    media_spend = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=(
            "Total advertiser media value consumed by this appearance."
        ),
    )

    platform_share_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("15.000"),
        help_text=(
            "Revenue-share percentage permanently locked when purchased."
        ),
    )

    platform_share_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=(
            "ATL's Hottest internal revenue allocation from media spend."
        ),
    )

    purchased_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchased_at", "-id"]
        verbose_name = "Advertising Campaign Spend"
        verbose_name_plural = "Advertising Campaign Spend"

        constraints = [
            models.CheckConstraint(
                condition=models.Q(slot_count__gte=1),
                name="ad_campaign_spend_slot_count_gte_one",
            ),
            models.CheckConstraint(
                condition=models.Q(locked_slot_price__gte=0),
                name="ad_campaign_spend_slot_price_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(media_spend__gte=0),
                name="ad_campaign_spend_media_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(platform_share_percent__gte=0),
                name="ad_campaign_spend_share_percent_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(platform_share_percent__lte=100),
                name="ad_campaign_spend_share_percent_lte_100",
            ),
            models.CheckConstraint(
                condition=models.Q(platform_share_amount__gte=0),
                name="ad_campaign_spend_share_amount_gte_zero",
            ),
        ]

    def __str__(self):
        return (
            f"{self.campaign} — "
            f"{self.slot_count} slot(s) — "
            f"${self.media_spend}"
        )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Advertising campaign spend entries are immutable."
            )

        super().save(*args, **kwargs)


def advertising_campaign_playout_spend(campaign):
    """
    Media budget actually consumed by H3 playout purchases.
    """
    total = (
        campaign.playout_spend_entries
        .aggregate(total=Sum("media_spend"))
        ["total"]
    )

    return total or Decimal("0.00")


def advertising_campaign_playout_remaining(campaign):
    """
    Remaining advertiser media value available to the playout allocator.

    Internal ATL's Hottest revenue allocation is deliberately NOT
    subtracted again.
    """
    total_budget = campaign.total_budget or Decimal("0.00")

    return (
        total_budget -
        advertising_campaign_playout_spend(campaign)
    )


def record_advertising_campaign_spend(
    *,
    campaign,
    creative,
    reservations,
    policy=None,
):
    """
    Create the immutable financial record for one complete appearance.

    Reservations must all:
      * belong to the same appearance
      * belong to the supplied campaign
      * use the same placement
      * use the same locked six-second price
    """

    if not reservations:
        raise ValidationError(
            "At least one playout reservation is required."
        )

    appearance_ids = {
        reservation.appearance_id
        for reservation in reservations
    }

    if len(appearance_ids) != 1:
        raise ValidationError(
            "Spend may only be recorded for one appearance at a time."
        )

    if any(
        reservation.campaign_id != campaign.pk
        for reservation in reservations
    ):
        raise ValidationError(
            "Every reservation must belong to the supplied campaign."
        )

    placements = {
        reservation.placement
        for reservation in reservations
    }

    if len(placements) != 1:
        raise ValidationError(
            "All appearance reservations must use one placement."
        )

    prices = {
        reservation.locked_slot_price
        for reservation in reservations
    }

    if len(prices) != 1:
        raise ValidationError(
            "All appearance reservations must share one locked slot price."
        )

    slot_price = next(iter(prices))
    slot_count = len(reservations)

    media_spend = (
        slot_price * Decimal(slot_count)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    remaining = advertising_campaign_playout_remaining(campaign)

    if media_spend > remaining:
        raise ValidationError(
            "This appearance exceeds the campaign's remaining media budget."
        )

    if policy is None:
        policy = AdvertisingRevenuePolicy.current()

    share_percent = (
        policy.platform_share_percent
        if policy is not None
        else Decimal("15.000")
    )

    platform_share = (
        media_spend *
        share_percent /
        Decimal("100")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return AdvertisingCampaignSpend.objects.create(
        campaign=campaign,
        creative=creative,
        appearance_id=next(iter(appearance_ids)),
        placement=next(iter(placements)),
        slot_count=slot_count,
        locked_slot_price=slot_price,
        media_spend=media_spend,
        platform_share_percent=share_percent,
        platform_share_amount=platform_share,
    )


# =====================================================================
# 008-H3B-1 — ADVERTISING INVENTORY OPPORTUNITY FINDER
# =====================================================================

def advertising_daypart_contains_datetime(daypart, moment):
    """
    Return True when moment's local clock time belongs to daypart.

    Supports both ordinary dayparts such as 09:00-17:00 and
    overnight dayparts such as 22:00-06:00.

    Equal start/end times represent a 24-hour daypart.
    """
    from django.utils import timezone

    local_moment = timezone.localtime(moment) if timezone.is_aware(moment) else moment
    clock = local_moment.time().replace(tzinfo=None)

    start = daypart.start_time
    end = daypart.end_time

    if start == end:
        return True

    if start < end:
        return start <= clock < end

    # Overnight window, for example 22:00 -> 06:00.
    return clock >= start or clock < end


def advertising_inventory_schedule_for_datetime(*, placement, moment):
    """
    Resolve the active inventory schedule controlling one placement
    at one exact datetime.

    Overnight dayparts require special weekday handling:
    01:00 Tuesday may belong to Monday's 22:00-06:00 schedule.
    """
    from datetime import timedelta

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    local_moment = timezone.localtime(moment) if timezone.is_aware(moment) else moment

    schedules = (
        AdvertisingInventorySchedule.objects
        .select_related("daypart")
        .filter(
            placement=placement,
            is_active=True,
            daypart__is_active=True,
        )
    )

    matches = []

    for schedule in schedules:
        daypart = schedule.daypart

        if not advertising_daypart_contains_datetime(daypart, local_moment):
            continue

        schedule_weekday = local_moment.weekday()

        # If an overnight daypart is being matched after midnight,
        # its schedule belongs to the previous calendar weekday.
        if (
            daypart.start_time > daypart.end_time
            and local_moment.time().replace(tzinfo=None) < daypart.end_time
        ):
            schedule_weekday = (
                local_moment - timedelta(days=1)
            ).weekday()

        if schedule.weekday == schedule_weekday:
            matches.append(schedule)

    if not matches:
        return None

    if len(matches) > 1:
        raise ValidationError(
            "More than one active advertising inventory schedule "
            "matches this placement and datetime."
        )

    return matches[0]


def find_advertising_inventory_opportunity(
    *,
    placement,
    creative,
    starts_at,
    campaign=None,
):
    """
    Read-only H3B opportunity lookup.

    Determine whether one complete creative appearance can begin at
    starts_at without:

      * leaving the campaign window,
      * crossing into another inventory schedule/daypart,
      * colliding with already reserved six-second inventory.

    No reservation or financial record is created here.
    """
    from datetime import timedelta
    from decimal import Decimal, ROUND_HALF_UP

    from django.core.exceptions import ValidationError

    if creative is None:
        raise ValidationError("A playout creative is required.")

    slot_count = (
        AdvertisingInventorySchedule
        .slots_required_for_duration(
            creative.duration_seconds
        )
    )

    slot_seconds = AdvertisingInventorySchedule.SLOT_SECONDS
    appearance_end = starts_at + timedelta(
        seconds=slot_count * slot_seconds
    )

    if campaign is not None:
        if campaign.starts_at and starts_at < campaign.starts_at:
            return {
                "available": False,
                "reason": "before_campaign_window",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
            }

        if campaign.ends_at and appearance_end > campaign.ends_at:
            return {
                "available": False,
                "reason": "after_campaign_window",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
            }

    schedule = advertising_inventory_schedule_for_datetime(
        placement=placement,
        moment=starts_at,
    )

    if schedule is None:
        return {
            "available": False,
            "reason": "no_inventory_schedule",
            "placement": placement,
            "starts_at": starts_at,
            "ends_at": appearance_end,
            "slot_count": slot_count,
        }

    slot_starts = [
        starts_at + timedelta(seconds=index * slot_seconds)
        for index in range(slot_count)
    ]

    # Every atomic unit in the appearance must resolve back to the
    # SAME schedule. This prevents an appearance from straddling a
    # daypart/rate boundary.
    for slot_start in slot_starts:
        slot_schedule = advertising_inventory_schedule_for_datetime(
            placement=placement,
            moment=slot_start,
        )

        if (
            slot_schedule is None
            or slot_schedule.pk != schedule.pk
        ):
            return {
                "available": False,
                "reason": "crosses_inventory_boundary",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
                "schedule": schedule,
            }

    collision_exists = (
        AdvertisingPlayoutReservation.objects
        .filter(
            placement=placement,
            slot_start__in=slot_starts,
        )
        .exclude(
            status=AdvertisingPlayoutReservation.STATUS_CANCELLED
        )
        .exists()
    )

    if collision_exists:
        return {
            "available": False,
            "reason": "inventory_collision",
            "placement": placement,
            "starts_at": starts_at,
            "ends_at": appearance_end,
            "slot_count": slot_count,
            "schedule": schedule,
        }

    slot_price = schedule.current_slot_price

    appearance_cost = (
        slot_price * Decimal(slot_count)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if campaign is not None:
        remaining = advertising_campaign_playout_remaining(campaign)

        if appearance_cost > remaining:
            return {
                "available": False,
                "reason": "insufficient_campaign_budget",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
                "schedule": schedule,
                "slot_price": slot_price,
                "appearance_cost": appearance_cost,
                "campaign_remaining": remaining,
            }

    return {
        "available": True,
        "reason": "available",
        "placement": placement,
        "starts_at": starts_at,
        "ends_at": appearance_end,
        "slot_count": slot_count,
        "schedule": schedule,
        "daypart": schedule.daypart,
        "slot_price": slot_price,
        "appearance_cost": appearance_cost,
        "slot_starts": slot_starts,
    }


# =====================================================================
# 008-H3B-1 — ADVERTISING INVENTORY OPPORTUNITY FINDER
# =====================================================================

def advertising_daypart_contains_datetime(daypart, moment):
    """
    Return True when moment's local clock time belongs to daypart.

    Supports both ordinary dayparts such as 09:00-17:00 and
    overnight dayparts such as 22:00-06:00.

    Equal start/end times represent a 24-hour daypart.
    """
    from django.utils import timezone

    local_moment = timezone.localtime(moment) if timezone.is_aware(moment) else moment
    clock = local_moment.time().replace(tzinfo=None)

    start = daypart.start_time
    end = daypart.end_time

    if start == end:
        return True

    if start < end:
        return start <= clock < end

    # Overnight window, for example 22:00 -> 06:00.
    return clock >= start or clock < end


def advertising_inventory_schedule_for_datetime(*, placement, moment):
    """
    Resolve the active inventory schedule controlling one placement
    at one exact datetime.

    Overnight dayparts require special weekday handling:
    01:00 Tuesday may belong to Monday's 22:00-06:00 schedule.
    """
    from datetime import timedelta

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    local_moment = timezone.localtime(moment) if timezone.is_aware(moment) else moment

    schedules = (
        AdvertisingInventorySchedule.objects
        .select_related("daypart")
        .filter(
            placement=placement,
            is_active=True,
            daypart__is_active=True,
        )
    )

    matches = []

    for schedule in schedules:
        daypart = schedule.daypart

        if not advertising_daypart_contains_datetime(daypart, local_moment):
            continue

        schedule_weekday = local_moment.weekday()

        # If an overnight daypart is being matched after midnight,
        # its schedule belongs to the previous calendar weekday.
        if (
            daypart.start_time > daypart.end_time
            and local_moment.time().replace(tzinfo=None) < daypart.end_time
        ):
            schedule_weekday = (
                local_moment - timedelta(days=1)
            ).weekday()

        if schedule.weekday == schedule_weekday:
            matches.append(schedule)

    if not matches:
        return None

    if len(matches) > 1:
        raise ValidationError(
            "More than one active advertising inventory schedule "
            "matches this placement and datetime."
        )

    return matches[0]


def find_advertising_inventory_opportunity(
    *,
    placement,
    creative,
    starts_at,
    campaign=None,
):
    """
    Read-only H3B opportunity lookup.

    Determine whether one complete creative appearance can begin at
    starts_at without:

      * leaving the campaign window,
      * crossing into another inventory schedule/daypart,
      * colliding with already reserved six-second inventory.

    No reservation or financial record is created here.
    """
    from datetime import timedelta
    from decimal import Decimal, ROUND_HALF_UP

    from django.core.exceptions import ValidationError

    if creative is None:
        raise ValidationError("A playout creative is required.")

    slot_count = (
        AdvertisingInventorySchedule
        .slots_required_for_duration(
            creative.duration_seconds
        )
    )

    slot_seconds = AdvertisingInventorySchedule.SLOT_SECONDS
    appearance_end = starts_at + timedelta(
        seconds=slot_count * slot_seconds
    )

    if campaign is not None:
        if campaign.starts_at and starts_at < campaign.starts_at:
            return {
                "available": False,
                "reason": "before_campaign_window",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
            }

        if campaign.ends_at and appearance_end > campaign.ends_at:
            return {
                "available": False,
                "reason": "after_campaign_window",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
            }

    schedule = advertising_inventory_schedule_for_datetime(
        placement=placement,
        moment=starts_at,
    )

    if schedule is None:
        return {
            "available": False,
            "reason": "no_inventory_schedule",
            "placement": placement,
            "starts_at": starts_at,
            "ends_at": appearance_end,
            "slot_count": slot_count,
        }

    slot_starts = [
        starts_at + timedelta(seconds=index * slot_seconds)
        for index in range(slot_count)
    ]

    # Every atomic unit in the appearance must resolve back to the
    # SAME schedule. This prevents an appearance from straddling a
    # daypart/rate boundary.
    for slot_start in slot_starts:
        slot_schedule = advertising_inventory_schedule_for_datetime(
            placement=placement,
            moment=slot_start,
        )

        if (
            slot_schedule is None
            or slot_schedule.pk != schedule.pk
        ):
            return {
                "available": False,
                "reason": "crosses_inventory_boundary",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
                "schedule": schedule,
            }

    collision_exists = (
        AdvertisingPlayoutReservation.objects
        .filter(
            placement=placement,
            slot_start__in=slot_starts,
        )
        .exclude(
            status=AdvertisingPlayoutReservation.STATUS_CANCELLED
        )
        .exists()
    )

    if collision_exists:
        return {
            "available": False,
            "reason": "inventory_collision",
            "placement": placement,
            "starts_at": starts_at,
            "ends_at": appearance_end,
            "slot_count": slot_count,
            "schedule": schedule,
        }

    slot_price = schedule.current_slot_price

    appearance_cost = (
        slot_price * Decimal(slot_count)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if campaign is not None:
        remaining = advertising_campaign_playout_remaining(campaign)

        if appearance_cost > remaining:
            return {
                "available": False,
                "reason": "insufficient_campaign_budget",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
                "schedule": schedule,
                "slot_price": slot_price,
                "appearance_cost": appearance_cost,
                "campaign_remaining": remaining,
            }

    return {
        "available": True,
        "reason": "available",
        "placement": placement,
        "starts_at": starts_at,
        "ends_at": appearance_end,
        "slot_count": slot_count,
        "schedule": schedule,
        "daypart": schedule.daypart,
        "slot_price": slot_price,
        "appearance_cost": appearance_cost,
        "slot_starts": slot_starts,
    }


# =====================================================================
# 008-H3B-1 — ADVERTISING INVENTORY OPPORTUNITY FINDER
# =====================================================================

def advertising_daypart_contains_datetime(daypart, moment):
    """
    Return True when moment's local clock time belongs to daypart.

    Supports both ordinary dayparts such as 09:00-17:00 and
    overnight dayparts such as 22:00-06:00.

    Equal start/end times represent a 24-hour daypart.
    """
    from django.utils import timezone

    local_moment = timezone.localtime(moment) if timezone.is_aware(moment) else moment
    clock = local_moment.time().replace(tzinfo=None)

    start = daypart.start_time
    end = daypart.end_time

    if start == end:
        return True

    if start < end:
        return start <= clock < end

    # Overnight window, for example 22:00 -> 06:00.
    return clock >= start or clock < end


def advertising_inventory_schedule_for_datetime(*, placement, moment):
    """
    Resolve the active inventory schedule controlling one placement
    at one exact datetime.

    Overnight dayparts require special weekday handling:
    01:00 Tuesday may belong to Monday's 22:00-06:00 schedule.
    """
    from datetime import timedelta

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    local_moment = timezone.localtime(moment) if timezone.is_aware(moment) else moment

    schedules = (
        AdvertisingInventorySchedule.objects
        .select_related("daypart")
        .filter(
            placement=placement,
            is_active=True,
            daypart__is_active=True,
        )
    )

    matches = []

    for schedule in schedules:
        daypart = schedule.daypart

        if not advertising_daypart_contains_datetime(daypart, local_moment):
            continue

        schedule_weekday = local_moment.weekday()

        # If an overnight daypart is being matched after midnight,
        # its schedule belongs to the previous calendar weekday.
        if (
            daypart.start_time > daypart.end_time
            and local_moment.time().replace(tzinfo=None) < daypart.end_time
        ):
            schedule_weekday = (
                local_moment - timedelta(days=1)
            ).weekday()

        if schedule.weekday == schedule_weekday:
            matches.append(schedule)

    if not matches:
        return None

    if len(matches) > 1:
        raise ValidationError(
            "More than one active advertising inventory schedule "
            "matches this placement and datetime."
        )

    return matches[0]


def find_advertising_inventory_opportunity(
    *,
    placement,
    creative,
    starts_at,
    campaign=None,
):
    """
    Read-only H3B opportunity lookup.

    Determine whether one complete creative appearance can begin at
    starts_at without:

      * leaving the campaign window,
      * crossing into another inventory schedule/daypart,
      * colliding with already reserved six-second inventory.

    No reservation or financial record is created here.
    """
    from datetime import timedelta
    from decimal import Decimal, ROUND_HALF_UP

    from django.core.exceptions import ValidationError

    if creative is None:
        raise ValidationError("A playout creative is required.")

    slot_count = (
        AdvertisingInventorySchedule
        .slots_required_for_duration(
            creative.duration_seconds
        )
    )

    slot_seconds = AdvertisingInventorySchedule.SLOT_SECONDS
    appearance_end = starts_at + timedelta(
        seconds=slot_count * slot_seconds
    )

    if campaign is not None:
        if campaign.starts_at and starts_at < campaign.starts_at:
            return {
                "available": False,
                "reason": "before_campaign_window",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
            }

        if campaign.ends_at and appearance_end > campaign.ends_at:
            return {
                "available": False,
                "reason": "after_campaign_window",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
            }

    schedule = advertising_inventory_schedule_for_datetime(
        placement=placement,
        moment=starts_at,
    )

    if schedule is None:
        return {
            "available": False,
            "reason": "no_inventory_schedule",
            "placement": placement,
            "starts_at": starts_at,
            "ends_at": appearance_end,
            "slot_count": slot_count,
        }

    slot_starts = [
        starts_at + timedelta(seconds=index * slot_seconds)
        for index in range(slot_count)
    ]

    # Every atomic unit in the appearance must resolve back to the
    # SAME schedule. This prevents an appearance from straddling a
    # daypart/rate boundary.
    for slot_start in slot_starts:
        slot_schedule = advertising_inventory_schedule_for_datetime(
            placement=placement,
            moment=slot_start,
        )

        if (
            slot_schedule is None
            or slot_schedule.pk != schedule.pk
        ):
            return {
                "available": False,
                "reason": "crosses_inventory_boundary",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
                "schedule": schedule,
            }

    collision_exists = (
        AdvertisingPlayoutReservation.objects
        .filter(
            placement=placement,
            slot_start__in=slot_starts,
        )
        .exclude(
            status=AdvertisingPlayoutReservation.STATUS_CANCELLED
        )
        .exists()
    )

    if collision_exists:
        return {
            "available": False,
            "reason": "inventory_collision",
            "placement": placement,
            "starts_at": starts_at,
            "ends_at": appearance_end,
            "slot_count": slot_count,
            "schedule": schedule,
        }

    slot_price = schedule.current_slot_price

    appearance_cost = (
        slot_price * Decimal(slot_count)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if campaign is not None:
        remaining = advertising_campaign_playout_remaining(campaign)

        if appearance_cost > remaining:
            return {
                "available": False,
                "reason": "insufficient_campaign_budget",
                "placement": placement,
                "starts_at": starts_at,
                "ends_at": appearance_end,
                "slot_count": slot_count,
                "schedule": schedule,
                "slot_price": slot_price,
                "appearance_cost": appearance_cost,
                "campaign_remaining": remaining,
            }

    return {
        "available": True,
        "reason": "available",
        "placement": placement,
        "starts_at": starts_at,
        "ends_at": appearance_end,
        "slot_count": slot_count,
        "schedule": schedule,
        "daypart": schedule.daypart,
        "slot_price": slot_price,
        "appearance_cost": appearance_cost,
        "slot_starts": slot_starts,
    }


# =====================================================================
# 008-H3B-2A — CAMPAIGN PACING + PURCHASE DECISION ENGINE
# =====================================================================

def advertising_campaign_pacing_snapshot(*, campaign, moment=None):
    """
    Return a read-only pacing snapshot for one advertising campaign.

    Linear pacing model:

        elapsed_fraction = elapsed campaign time / total campaign time
        target_spend     = total media budget * elapsed_fraction
        pacing_delta     = target_spend - actual playout spend

    Positive pacing_delta = campaign is behind pace.
    Zero                  = exactly on pace.
    Negative              = campaign is ahead of pace.

    No database mutation occurs here.
    """
    from decimal import Decimal, ROUND_HALF_UP

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if moment is None:
        moment = timezone.now()

    if campaign.starts_at is None or campaign.ends_at is None:
        raise ValidationError(
            "Campaign pacing requires both starts_at and ends_at."
        )

    if campaign.ends_at <= campaign.starts_at:
        raise ValidationError(
            "Campaign end time must be after campaign start time."
        )

    total_budget = (
        campaign.total_budget or Decimal("0.00")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    actual_spend = (
        advertising_campaign_playout_spend(campaign)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    remaining_budget = (
        total_budget - actual_spend
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    total_seconds = Decimal(
        str(
            (
                campaign.ends_at - campaign.starts_at
            ).total_seconds()
        )
    )

    if moment <= campaign.starts_at:
        elapsed_fraction = Decimal("0")
        phase = "before_campaign"
    elif moment >= campaign.ends_at:
        elapsed_fraction = Decimal("1")
        phase = "after_campaign"
    else:
        elapsed_seconds = Decimal(
            str(
                (
                    moment - campaign.starts_at
                ).total_seconds()
            )
        )

        elapsed_fraction = (
            elapsed_seconds / total_seconds
        )

        phase = "active"

    # Keep the mathematical fraction bounded even if the supplied
    # moment falls outside the campaign window.
    elapsed_fraction = max(
        Decimal("0"),
        min(Decimal("1"), elapsed_fraction),
    )

    target_spend = (
        total_budget * elapsed_fraction
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    pacing_delta = (
        target_spend - actual_spend
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if pacing_delta > 0:
        pacing_status = "under"
    elif pacing_delta < 0:
        pacing_status = "over"
    else:
        pacing_status = "on"

    remaining_seconds = max(
        Decimal("0"),
        total_seconds * (
            Decimal("1") - elapsed_fraction
        ),
    )

    return {
        "campaign": campaign,
        "moment": moment,
        "phase": phase,
        "total_budget": total_budget,
        "actual_spend": actual_spend,
        "remaining_budget": remaining_budget,
        "elapsed_fraction": elapsed_fraction,
        "remaining_fraction": (
            Decimal("1") - elapsed_fraction
        ),
        "target_spend": target_spend,
        "pacing_delta": pacing_delta,
        "pacing_status": pacing_status,
        "total_seconds": total_seconds,
        "remaining_seconds": remaining_seconds,
    }


def decide_advertising_opportunity_purchase(
    *,
    campaign,
    opportunity,
    moment=None,
):
    """
    Read-only decision for whether H3B should purchase one opportunity.

    H3B-2A intentionally does NOT:
      * reserve inventory,
      * create spend rows,
      * modify campaign data,
      * touch the billboard/player.

    Version 1 uses conservative linear pacing.

    A purchase is approved only when:
      * the campaign is currently active by time,
      * H3B-1 says the opportunity is available,
      * the appearance fits remaining campaign budget,
      * the campaign is behind its linear spend target,
      * buying the appearance will not overshoot that target by more
        than the cost of one appearance.

    That final rule permits the engine to catch up in indivisible
    appearance-sized increments without demanding impossible
    fractional purchases.
    """
    from decimal import Decimal, ROUND_HALF_UP

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if moment is None:
        moment = timezone.now()

    snapshot = advertising_campaign_pacing_snapshot(
        campaign=campaign,
        moment=moment,
    )

    def result(*, purchase, reason, appearance_cost=Decimal("0.00")):
        return {
            "purchase": purchase,
            "reason": reason,
            "appearance_cost": appearance_cost,
            "campaign_remaining": snapshot["remaining_budget"],
            "target_spend": snapshot["target_spend"],
            "actual_spend": snapshot["actual_spend"],
            "pacing_delta": snapshot["pacing_delta"],
            "pacing_status": snapshot["pacing_status"],
            "phase": snapshot["phase"],
            "snapshot": snapshot,
            "opportunity": opportunity,
        }

    if snapshot["phase"] == "before_campaign":
        return result(
            purchase=False,
            reason="campaign_not_started",
        )

    if snapshot["phase"] == "after_campaign":
        return result(
            purchase=False,
            reason="campaign_ended",
        )

    if not opportunity:
        raise ValidationError(
            "An H3B-1 advertising opportunity is required."
        )

    if not opportunity.get("available", False):
        return result(
            purchase=False,
            reason=opportunity.get(
                "reason",
                "opportunity_unavailable",
            ),
        )

    raw_cost = opportunity.get("appearance_cost")

    if raw_cost is None:
        raise ValidationError(
            "Available opportunity must include appearance_cost."
        )

    appearance_cost = Decimal(raw_cost).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if appearance_cost < 0:
        raise ValidationError(
            "Opportunity appearance cost cannot be negative."
        )

    if appearance_cost > snapshot["remaining_budget"]:
        return result(
            purchase=False,
            reason="insufficient_campaign_budget",
            appearance_cost=appearance_cost,
        )

    if snapshot["pacing_delta"] <= 0:
        return result(
            purchase=False,
            reason="not_behind_pace",
            appearance_cost=appearance_cost,
        )

    spend_after_purchase = (
        snapshot["actual_spend"] + appearance_cost
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # An appearance is indivisible. Permit one appearance-sized step
    # across the exact target, but never permit a larger leap.
    maximum_paced_spend = (
        snapshot["target_spend"] + appearance_cost
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if spend_after_purchase > maximum_paced_spend:
        return result(
            purchase=False,
            reason="would_exceed_pacing_allowance",
            appearance_cost=appearance_cost,
        )

    return result(
        purchase=True,
        reason="purchase",
        appearance_cost=appearance_cost,
    )


# =====================================================================
# 008-H3B-2B — ATOMIC ADVERTISING AUTO-PURCHASE TRANSACTION
# =====================================================================

def execute_advertising_opportunity_purchase(
    *,
    campaign,
    creative,
    placement,
    starts_at,
    moment=None,
    policy=None,
):
    """
    Atomically purchase one complete advertising appearance.

    Pipeline:

        H3B-1 recheck opportunity
            ↓
        H3B-2A pacing decision
            ↓
        BEGIN OUTER TRANSACTION
            ↓
        lock campaign row
            ↓
        H3B-1 recheck inventory + current price
            ↓
        H3B-2A recheck pacing + remaining budget
            ↓
        H2 reserve all consecutive six-second units
            ↓
        H3A create immutable spend record
            ↓
        COMMIT

    Any exception after the outer transaction begins rolls back BOTH
    the reservations and spend record.

    This function does not touch the live billboard/player.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.utils import timezone

    if campaign is None:
        raise ValidationError(
            "An advertising campaign is required."
        )

    if creative is None:
        raise ValidationError(
            "An advertising playout creative is required."
        )

    if not placement:
        raise ValidationError(
            "An advertising placement is required."
        )

    if starts_at is None:
        raise ValidationError(
            "An advertising appearance start time is required."
        )

    if moment is None:
        moment = timezone.now()

    # -------------------------------------------------------------
    # Fast read-only preflight.
    #
    # This avoids opening a write transaction when the opportunity
    # obviously cannot be purchased. Nothing here is authoritative;
    # everything important is checked again after locking.
    # -------------------------------------------------------------
    preflight_opportunity = find_advertising_inventory_opportunity(
        placement=placement,
        creative=creative,
        starts_at=starts_at,
        campaign=campaign,
    )

    preflight_decision = decide_advertising_opportunity_purchase(
        campaign=campaign,
        opportunity=preflight_opportunity,
        moment=moment,
    )

    if not preflight_decision["purchase"]:
        return {
            "purchased": False,
            "reason": preflight_decision["reason"],
            "campaign": campaign,
            "creative": creative,
            "placement": placement,
            "starts_at": starts_at,
            "opportunity": preflight_opportunity,
            "decision": preflight_decision,
            "reservations": [],
            "spend": None,
        }

    with transaction.atomic():

        # Serialize purchases against this campaign. This protects the
        # remaining-budget calculation when multiple workers attempt to
        # buy inventory for the same campaign simultaneously.
        locked_campaign = (
            AdvertisingCampaign.objects
            .select_for_update()
            .get(pk=campaign.pk)
        )

        # ---------------------------------------------------------
        # AUTHORITATIVE H3B-1 RECHECK
        # ---------------------------------------------------------
        opportunity = find_advertising_inventory_opportunity(
            placement=placement,
            creative=creative,
            starts_at=starts_at,
            campaign=locked_campaign,
        )

        # ---------------------------------------------------------
        # AUTHORITATIVE H3B-2A RECHECK
        # ---------------------------------------------------------
        decision = decide_advertising_opportunity_purchase(
            campaign=locked_campaign,
            opportunity=opportunity,
            moment=moment,
        )

        if not decision["purchase"]:
            return {
                "purchased": False,
                "reason": decision["reason"],
                "campaign": locked_campaign,
                "creative": creative,
                "placement": placement,
                "starts_at": starts_at,
                "opportunity": opportunity,
                "decision": decision,
                "reservations": [],
                "spend": None,
            }

        slot_price = opportunity.get("slot_price")

        if slot_price is None:
            raise ValidationError(
                "Purchasable opportunity is missing its locked slot price."
            )

        # ---------------------------------------------------------
        # H2 — ATOMIC CONSECUTIVE SIX-SECOND RESERVATION
        # ---------------------------------------------------------
        reservations = reserve_advertising_appearance(
            placement=placement,
            creative=creative,
            starts_at=starts_at,
            locked_slot_price=slot_price,
            campaign=locked_campaign,
        )

        if not reservations:
            raise ValidationError(
                "Advertising purchase created no reservations."
            )

        appearance_ids = {
            reservation.appearance_id
            for reservation in reservations
        }

        if len(appearance_ids) != 1:
            raise ValidationError(
                "Advertising purchase reservations do not share "
                "one appearance identifier."
            )

        appearance_id = next(iter(appearance_ids))

        # Application-level idempotency protection. The outer atomic
        # transaction ensures that if this guard or H3A fails, H2's
        # reservations are rolled back with it.
        if AdvertisingCampaignSpend.objects.filter(
            campaign=locked_campaign,
            appearance_id=appearance_id,
        ).exists():
            raise ValidationError(
                "Spend has already been recorded for this appearance."
            )

        # ---------------------------------------------------------
        # H3A — IMMUTABLE CAMPAIGN SPEND + PLATFORM SHARE
        # ---------------------------------------------------------
        spend = record_advertising_campaign_spend(
            campaign=locked_campaign,
            creative=creative,
            reservations=reservations,
            policy=policy,
        )

        if spend.appearance_id != appearance_id:
            raise ValidationError(
                "Spend record appearance does not match reservations."
            )

        expected_cost = opportunity["appearance_cost"]

        if spend.media_spend != expected_cost:
            raise ValidationError(
                "Recorded campaign spend does not match the "
                "authoritative opportunity cost."
            )

        return {
            "purchased": True,
            "reason": "purchased",
            "campaign": locked_campaign,
            "creative": creative,
            "placement": placement,
            "starts_at": starts_at,
            "opportunity": opportunity,
            "decision": decision,
            "reservations": reservations,
            "spend": spend,
            "appearance_id": appearance_id,
        }


# =========================================================
# 008-H3B-3A
# Advertising Campaign Creative Assignment
# =========================================================

class AdvertisingCampaignCreative(models.Model):
    """
    Explicit authorization linking a paid advertising campaign to a
    playout creative.

    The autonomous advertising controller may only purchase paid
    inventory using creatives that have an active assignment for the
    campaign.

    Rotation weight and assignment priority live here rather than on
    AdvertisingPlayoutCreative because the same creative may eventually
    participate in different campaigns with different delivery rules.
    """

    campaign = models.ForeignKey(
        "AdvertisingCampaign",
        on_delete=models.CASCADE,
        related_name="creative_assignments",
    )

    creative = models.ForeignKey(
        "AdvertisingPlayoutCreative",
        on_delete=models.PROTECT,
        related_name="campaign_assignments",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "Only active assignments may be selected by automated "
            "campaign execution."
        ),
    )

    rotation_weight = models.PositiveIntegerField(
        default=100,
        help_text=(
            "Relative campaign-specific delivery weight. Higher values "
            "may receive proportionally more appearances."
        ),
    )

    priority = models.PositiveIntegerField(
        default=100,
        db_index=True,
        help_text=(
            "Campaign-specific creative priority. Lower values are "
            "considered first when priorities differ."
        ),
    )

    approved_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text=(
            "Time this creative was authorized for campaign delivery."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "priority",
            "-rotation_weight",
            "id",
        ]

        verbose_name = "Advertising Campaign Creative"
        verbose_name_plural = "Advertising Campaign Creatives"

        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "creative"],
                name="unique_ad_campaign_creative_assignment",
            ),
            models.CheckConstraint(
                condition=models.Q(rotation_weight__gte=1),
                name="ad_campaign_creative_rotation_weight_gte_one",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__gte=1),
                name="ad_campaign_creative_priority_gte_one",
            ),
        ]

    def __str__(self):
        return (
            f"{self.campaign.campaign_name} — "
            f"{self.creative.name}"
        )

    def clean(self):
        super().clean()

        if (
            self.creative_id
            and self.creative.creative_type
            != AdvertisingPlayoutCreative.TYPE_PAID
        ):
            raise ValidationError({
                "creative": (
                    "Campaign creative assignments may only authorize "
                    "paid advertising creatives."
                )
            })

    def is_eligible_at(self, moment=None):
        """
        Return True only when both the assignment and underlying paid
        creative are currently eligible for automated campaign use.
        """

        moment = moment or timezone.now()

        if not self.is_active:
            return False

        creative = self.creative

        if creative.creative_type != AdvertisingPlayoutCreative.TYPE_PAID:
            return False

        if not creative.is_active:
            return False

        if creative.starts_at and moment < creative.starts_at:
            return False

        if creative.ends_at and moment >= creative.ends_at:
            return False

        return True


def advertising_campaign_eligible_creative_assignments(
    *,
    campaign,
    moment=None,
):
    """
    Return active, explicitly authorized paid creative assignments for
    one campaign at the supplied moment.

    This is the authorization boundary used by the future H3B-3B
    autonomous shopping controller.
    """

    moment = moment or timezone.now()

    assignments = (
        campaign.creative_assignments
        .select_related("creative")
        .filter(
            is_active=True,
            creative__creative_type=AdvertisingPlayoutCreative.TYPE_PAID,
            creative__is_active=True,
        )
        .order_by(
            "priority",
            "-rotation_weight",
            "id",
        )
    )

    return [
        assignment
        for assignment in assignments
        if assignment.is_eligible_at(moment)
    ]


def advertising_campaign_creative_is_authorized(
    *,
    campaign,
    creative,
    moment=None,
):
    """
    Boolean authorization check for autonomous paid advertising.

    Historical reservation/spend relationships are deliberately NOT
    treated as authorization. The campaign must possess a current,
    active AdvertisingCampaignCreative assignment.
    """

    moment = moment or timezone.now()

    assignment = (
        campaign.creative_assignments
        .select_related("creative")
        .filter(
            creative=creative,
            is_active=True,
        )
        .first()
    )

    if assignment is None:
        return False

    return assignment.is_eligible_at(moment)


# =====================================================================
# 008-H3B-3B — AUTOMATED ADVERTISING SHOPPING CONTROLLER
# =====================================================================

def advertising_campaign_current_properties(
    *,
    campaign,
    moment=None,
):
    """
    Return the campaign's currently usable purchased advertising properties.

    This is intentionally campaign-owned inventory only. H3B-3B may not
    autonomously shop placements the advertiser did not purchase.
    """
    from decimal import Decimal

    from django.utils import timezone

    moment = moment or timezone.now()

    properties = (
        campaign.billboard_ads
        .filter(is_active=True)
        .order_by(
            "priority",
            "-rotation_weight",
            "id",
        )
    )

    eligible = []

    for property_ad in properties:
        allocated = property_ad.allocated_budget or Decimal("0")
        minimum = property_ad.minimum_spend or Decimal("0")

        if allocated < minimum:
            continue

        if property_ad.starts_at and moment < property_ad.starts_at:
            continue

        if property_ad.ends_at and moment >= property_ad.ends_at:
            continue

        eligible.append(property_ad)

    return eligible


def _advertising_next_six_second_boundary(moment):
    """
    Move a datetime onto the next six-second inventory boundary.

    If already exactly aligned, the supplied moment is returned.
    """
    from datetime import timedelta

    slot_seconds = AdvertisingInventorySchedule.SLOT_SECONDS

    if moment.microsecond:
        moment = moment.replace(microsecond=0) + timedelta(seconds=1)

    remainder = moment.second % slot_seconds

    if remainder:
        moment += timedelta(seconds=(slot_seconds - remainder))

    return moment


def find_automated_advertising_purchase_candidates(
    *,
    campaign,
    moment=None,
    lookahead_minutes=60,
):
    """
    Read-only H3B-3B candidate discovery.

    Search:

        campaign purchased properties
            x
        campaign-authorized paid creatives
            x
        future six-second inventory

    Candidate discovery never reserves inventory and never creates spend.

    Version 1 searches forward in six-second increments and returns every
    candidate that H3B-1 reports available AND H3B-2A says pacing permits.

    The final controller will buy at most ONE candidate per invocation.
    """
    from datetime import timedelta

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if campaign is None:
        raise ValidationError(
            "An advertising campaign is required."
        )

    if lookahead_minutes <= 0:
        raise ValidationError(
            "Automated shopping lookahead must be greater than zero."
        )

    moment = moment or timezone.now()

    if campaign.status != AdvertisingCampaign.STATUS_ACTIVE:
        return []

    snapshot = advertising_campaign_pacing_snapshot(
        campaign=campaign,
        moment=moment,
    )

    if snapshot["phase"] != "active":
        return []

    if snapshot["pacing_delta"] <= 0:
        return []

    properties = advertising_campaign_current_properties(
        campaign=campaign,
        moment=moment,
    )

    if not properties:
        return []

    assignments = advertising_campaign_eligible_creative_assignments(
        campaign=campaign,
        moment=moment,
    )

    if not assignments:
        return []

    search_start = _advertising_next_six_second_boundary(moment)

    search_end = search_start + timedelta(
        minutes=lookahead_minutes
    )

    if campaign.ends_at:
        search_end = min(search_end, campaign.ends_at)

    candidates = []

    slot_step = timedelta(
        seconds=AdvertisingInventorySchedule.SLOT_SECONDS
    )

    # Avoid duplicate searches when a campaign happens to contain more
    # than one BillboardAd record for the same placement.
    placement_properties = {}

    for property_ad in properties:
        current = placement_properties.get(property_ad.placement)

        if current is None:
            placement_properties[property_ad.placement] = property_ad
            continue

        current_key = (
            current.priority,
            -current.rotation_weight,
            current.pk,
        )
        candidate_key = (
            property_ad.priority,
            -property_ad.rotation_weight,
            property_ad.pk,
        )

        if candidate_key < current_key:
            placement_properties[property_ad.placement] = property_ad

    ordered_properties = sorted(
        placement_properties.values(),
        key=lambda property_ad: (
            property_ad.priority,
            -property_ad.rotation_weight,
            property_ad.pk,
        ),
    )

    for property_ad in ordered_properties:
        for assignment in assignments:
            creative = assignment.creative
            starts_at = search_start

            while starts_at < search_end:
                opportunity = find_advertising_inventory_opportunity(
                    placement=property_ad.placement,
                    creative=creative,
                    starts_at=starts_at,
                    campaign=campaign,
                )

                if opportunity.get("available", False):
                    decision = decide_advertising_opportunity_purchase(
                        campaign=campaign,
                        opportunity=opportunity,
                        moment=moment,
                    )

                    if decision["purchase"]:
                        candidates.append({
                            "campaign": campaign,
                            "property": property_ad,
                            "assignment": assignment,
                            "creative": creative,
                            "placement": property_ad.placement,
                            "starts_at": starts_at,
                            "opportunity": opportunity,
                            "decision": decision,
                        })

                        # We only need the earliest buyable time for each
                        # property/creative pair in this controller pass.
                        break

                starts_at += slot_step

    return candidates


def choose_automated_advertising_purchase_candidate(
    *,
    candidates,
):
    """
    Deterministically choose ONE H3B-3B candidate.

    Ranking v1:

      1. earliest available inventory
      2. property priority
      3. campaign creative priority
      4. higher property rotation weight
      5. higher creative rotation weight
      6. lower appearance cost
      7. stable database identifiers

    Rotation weights are preserved in the ranking without introducing
    randomness. A later controller can add delivery-history-aware weighted
    rotation without changing the campaign/creative ownership architecture.
    """
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda candidate: (
            candidate["starts_at"],
            candidate["property"].priority,
            candidate["assignment"].priority,
            -candidate["property"].rotation_weight,
            -candidate["assignment"].rotation_weight,
            candidate["opportunity"]["appearance_cost"],
            candidate["property"].pk,
            candidate["assignment"].pk,
        ),
    )


def run_automated_advertising_shopper(
    *,
    campaign,
    moment=None,
    lookahead_minutes=60,
    policy=None,
):
    """
    H3B-3B autonomous advertising shopping controller.

    ONE invocation may purchase AT MOST ONE complete appearance.

    The controller itself never writes reservation or spend rows.
    The winning candidate is handed to H3B-2B, which remains the
    authoritative atomic transaction boundary.

    Pipeline:

        active campaign
            ↓
        active campaign window
            ↓
        behind pacing target
            ↓
        current purchased properties
            ↓
        authorized H3B-3A creatives
            ↓
        search future six-second inventory
            ↓
        H3B-1 opportunity
            ↓
        H3B-2A purchase decision
            ↓
        deterministic candidate selection
            ↓
        H3B-2B atomic purchase
            ↓
        STOP
    """
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if campaign is None:
        raise ValidationError(
            "An advertising campaign is required."
        )

    moment = moment or timezone.now()

    def stopped(reason, **extra):
        result = {
            "purchased": False,
            "reason": reason,
            "campaign": campaign,
            "moment": moment,
            "candidate": None,
            "candidates_considered": 0,
            "purchase_result": None,
        }
        result.update(extra)
        return result

    # -------------------------------------------------------------
    # CAMPAIGN AUTHORIZATION GATE
    # -------------------------------------------------------------
    if campaign.status != AdvertisingCampaign.STATUS_ACTIVE:
        return stopped("campaign_not_active")

    # -------------------------------------------------------------
    # PACING / WINDOW GATE
    # -------------------------------------------------------------
    snapshot = advertising_campaign_pacing_snapshot(
        campaign=campaign,
        moment=moment,
    )

    if snapshot["phase"] == "before_campaign":
        return stopped(
            "campaign_not_started",
            snapshot=snapshot,
        )

    if snapshot["phase"] == "after_campaign":
        return stopped(
            "campaign_ended",
            snapshot=snapshot,
        )

    if snapshot["remaining_budget"] <= 0:
        return stopped(
            "campaign_budget_exhausted",
            snapshot=snapshot,
        )

    if snapshot["pacing_delta"] <= 0:
        return stopped(
            "not_behind_pace",
            snapshot=snapshot,
        )

    # -------------------------------------------------------------
    # PROPERTY AUTHORIZATION GATE
    # -------------------------------------------------------------
    properties = advertising_campaign_current_properties(
        campaign=campaign,
        moment=moment,
    )

    if not properties:
        return stopped(
            "no_current_campaign_properties",
            snapshot=snapshot,
        )

    # -------------------------------------------------------------
    # CREATIVE AUTHORIZATION GATE
    # -------------------------------------------------------------
    assignments = advertising_campaign_eligible_creative_assignments(
        campaign=campaign,
        moment=moment,
    )

    if not assignments:
        return stopped(
            "no_authorized_campaign_creatives",
            snapshot=snapshot,
        )

    # -------------------------------------------------------------
    # SHOP
    # -------------------------------------------------------------
    candidates = find_automated_advertising_purchase_candidates(
        campaign=campaign,
        moment=moment,
        lookahead_minutes=lookahead_minutes,
    )

    if not candidates:
        return stopped(
            "no_buyable_inventory",
            snapshot=snapshot,
        )

    winner = choose_automated_advertising_purchase_candidate(
        candidates=candidates,
    )

    if winner is None:
        return stopped(
            "no_buyable_inventory",
            snapshot=snapshot,
        )

    # Defense in depth:
    # Never trust a candidate merely because discovery produced it.
    if not advertising_campaign_creative_is_authorized(
        campaign=campaign,
        creative=winner["creative"],
        moment=moment,
    ):
        return stopped(
            "creative_authorization_changed",
            snapshot=snapshot,
            candidates_considered=len(candidates),
        )

    current_property_ids = {
        property_ad.pk
        for property_ad in advertising_campaign_current_properties(
            campaign=campaign,
            moment=moment,
        )
    }

    if winner["property"].pk not in current_property_ids:
        return stopped(
            "property_authorization_changed",
            snapshot=snapshot,
            candidates_considered=len(candidates),
        )

    # -------------------------------------------------------------
    # H3B-2B IS THE ONLY MONEY/RESERVATION WRITE PATH
    # -------------------------------------------------------------
    purchase_result = execute_advertising_opportunity_purchase(
        campaign=campaign,
        creative=winner["creative"],
        placement=winner["placement"],
        starts_at=winner["starts_at"],
        moment=moment,
        policy=policy,
    )

    return {
        "purchased": purchase_result["purchased"],
        "reason": purchase_result["reason"],
        "campaign": campaign,
        "moment": moment,
        "snapshot": snapshot,
        "candidate": winner,
        "candidates_considered": len(candidates),
        "purchase_result": purchase_result,
    }


# =====================================================================
# 008-H3B-3C — AUTONOMOUS ADVERTISING SHOPPING RUNNER
# =====================================================================

def advertising_campaign_runner_queryset(*, moment=None):
    """
    Return campaigns eligible to receive an autonomous shopping pass.

    This is deliberately a cheap database-level gate.

    H3B-3B remains responsible for the authoritative campaign window,
    pacing, budget, property, creative, inventory, and purchase checks.

    A campaign must:
      * be ACTIVE
      * have started
      * not have ended

    Campaigns are processed deterministically by end time and primary key.
    """
    from django.db.models import Q
    from django.utils import timezone

    moment = moment or timezone.now()

    return (
        AdvertisingCampaign.objects
        .filter(
            status=AdvertisingCampaign.STATUS_ACTIVE,
            starts_at__lte=moment,
        )
        .filter(
            Q(ends_at__isnull=True) |
            Q(ends_at__gt=moment)
        )
        .order_by(
            "ends_at",
            "id",
        )
    )


def run_autonomous_advertising_shopping_pass(
    *,
    moment=None,
    lookahead_minutes=60,
    policy=None,
    campaign_limit=None,
):
    """
    H3B-3C platform-wide autonomous shopping runner.

    Run one isolated H3B-3B shopping attempt for each currently eligible
    advertising campaign.

    CRITICAL SAFETY RULE:

        ONE RUNNER PASS
            x
        ONE CAMPAIGN
            =
        MAXIMUM ONE PURCHASED APPEARANCE

    H3B-3C never creates reservations or financial records directly.
    Every purchase must flow through:

        H3B-3C
            ↓
        H3B-3B autonomous shopper
            ↓
        H3B-2B atomic purchase
            ↓
        H2 six-second reservation ledger
            ↓
        H3A immutable campaign spend ledger

    Failure isolation:
        An exception raised while processing one campaign is captured in
        that campaign's runner result. Remaining campaigns continue.

    campaign_limit:
        Optional operational cap on the number of campaigns processed in
        this pass. This limits campaigns attempted — not purchases.
    """
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    moment = moment or timezone.now()

    if lookahead_minutes <= 0:
        raise ValidationError(
            "Autonomous shopping lookahead must be greater than zero."
        )

    if campaign_limit is not None:
        if (
            isinstance(campaign_limit, bool)
            or not isinstance(campaign_limit, int)
            or campaign_limit <= 0
        ):
            raise ValidationError(
                "Campaign limit must be a positive integer."
            )

    campaigns = advertising_campaign_runner_queryset(
        moment=moment,
    )

    if campaign_limit is not None:
        campaigns = campaigns[:campaign_limit]

    campaign_results = []

    purchased_count = 0
    skipped_count = 0
    failed_count = 0

    for campaign in campaigns:
        try:
            result = run_automated_advertising_shopper(
                campaign=campaign,
                moment=moment,
                lookahead_minutes=lookahead_minutes,
                policy=policy,
            )

        except Exception as exc:
            # Campaign-level containment is intentional here.
            #
            # A malformed or unexpectedly failing campaign must never stop
            # autonomous execution for every other advertiser.
            failed_count += 1

            campaign_results.append({
                "campaign": campaign,
                "campaign_id": campaign.pk,
                "campaign_name": campaign.campaign_name,
                "status": "failed",
                "purchased": False,
                "reason": "campaign_runner_exception",
                "shopper_result": None,
                "exception_type": exc.__class__.__name__,
                "exception_message": str(exc),
            })

            continue

        if result["purchased"]:
            purchased_count += 1
            status = "purchased"
        else:
            skipped_count += 1
            status = "skipped"

        campaign_results.append({
            "campaign": campaign,
            "campaign_id": campaign.pk,
            "campaign_name": campaign.campaign_name,
            "status": status,
            "purchased": result["purchased"],
            "reason": result["reason"],
            "shopper_result": result,
            "exception_type": None,
            "exception_message": "",
        })

    processed_count = len(campaign_results)

    return {
        "moment": moment,
        "lookahead_minutes": lookahead_minutes,
        "campaign_limit": campaign_limit,
        "processed_count": processed_count,
        "purchased_count": purchased_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "campaign_results": campaign_results,
    }


# =====================================================================
# 008-H3B-4A — AUTONOMOUS SHOPPING EXECUTION SAFETY
# =====================================================================

class AdvertisingShoppingRunnerLock(models.Model):
    """
    Singleton lease protecting the platform-wide autonomous advertising
    shopping runner from overlapping execution.

    The lock is a LEASE, not a permanent boolean mutex.

    Why:
        A worker may crash, restart, or be killed without executing normal
        cleanup. A permanent boolean lock could strand autonomous buying
        forever.

    lease_expires_at therefore allows a later worker to recover a stale lock.

    Lock acquisition is performed through a conditional database UPDATE.
    The update succeeds only when the lease is currently available.

    This gives the runner an atomic claim operation without depending solely
    on SELECT ... FOR UPDATE semantics, which differ between SQLite
    development and PostgreSQL production.
    """

    SINGLETON_KEY = "autonomous_advertising_shopper"

    key = models.CharField(
        max_length=100,
        unique=True,
        default=SINGLETON_KEY,
        editable=False,
    )

    owner_token = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        editable=False,
        help_text=(
            "Unique token identifying the execution currently holding "
            "the autonomous shopping lease."
        ),
    )

    acquired_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        editable=False,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Advertising Shopping Runner Lock"
        verbose_name_plural = "Advertising Shopping Runner Lock"

    def __str__(self):
        if self.owner_token:
            return (
                f"Advertising shopping runner lock — "
                f"{self.owner_token}"
            )

        return "Advertising shopping runner lock — available"


class AdvertisingShoppingExecution(models.Model):
    """
    Durable audit record for one attempt to execute H3B-3C.

    This ledger records operational execution — it does NOT replace the
    H3A immutable financial spend ledger.

    Financial truth remains:

        H3B-2B atomic purchase
            ↓
        H2 reservation rows
            ↓
        H3A campaign spend ledger

    H3B-4A records when the autonomous platform runner attempted to operate,
    whether it obtained the execution lease, and the aggregate H3B-3C result.
    """

    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_LOCKED_OUT = "locked_out"

    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_LOCKED_OUT, "Locked Out"),
    ]

    execution_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        db_index=True,
    )

    started_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Lease expiration assigned when this execution acquired "
            "the autonomous shopping runner lock."
        ),
    )

    lookahead_minutes = models.PositiveIntegerField(
        default=60,
    )

    campaign_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    processed_count = models.PositiveIntegerField(
        default=0,
    )

    purchased_count = models.PositiveIntegerField(
        default=0,
    )

    skipped_count = models.PositiveIntegerField(
        default=0,
    )

    failed_count = models.PositiveIntegerField(
        default=0,
    )

    failure_type = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    failure_message = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-started_at", "-id"]
        verbose_name = "Advertising Shopping Execution"
        verbose_name_plural = "Advertising Shopping Executions"

        constraints = [
            models.CheckConstraint(
                condition=models.Q(lookahead_minutes__gte=1),
                name="ad_shop_execution_lookahead_gte_one",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(campaign_limit__isnull=True) |
                    models.Q(campaign_limit__gte=1)
                ),
                name="ad_shop_execution_campaign_limit_valid",
            ),
        ]

    def __str__(self):
        return (
            f"{self.execution_id} — "
            f"{self.get_status_display()} — "
            f"{self.started_at}"
        )


def ensure_advertising_shopping_runner_lock():
    """
    Ensure the singleton lock row exists.

    This function intentionally does not claim the lock.
    """
    lock, _ = AdvertisingShoppingRunnerLock.objects.get_or_create(
        key=AdvertisingShoppingRunnerLock.SINGLETON_KEY,
    )

    return lock


def acquire_advertising_shopping_runner_lock(
    *,
    owner_token,
    moment=None,
    lease_seconds=300,
):
    """
    Atomically attempt to acquire the autonomous shopping runner lease.

    Returns:
        {
            "acquired": bool,
            "lock": AdvertisingShoppingRunnerLock,
            "owner_token": UUID,
            "lease_expires_at": datetime | None,
        }

    The database UPDATE is conditional:

        owner_token IS NULL
            OR
        lease_expires_at IS NULL
            OR
        lease_expires_at <= now

    Therefore two workers racing for the same available lease cannot both
    successfully update the row under normal database atomic-update
    guarantees.

    The owner token also protects release: one worker may never release
    another worker's lease.
    """
    from datetime import timedelta

    from django.core.exceptions import ValidationError
    from django.db import IntegrityError
    from django.db.models import Q
    from django.utils import timezone

    moment = moment or timezone.now()

    if owner_token is None:
        raise ValidationError(
            "An owner token is required to acquire the advertising "
            "shopping runner lock."
        )

    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or lease_seconds <= 0
    ):
        raise ValidationError(
            "Lease seconds must be a positive integer."
        )

    # Bootstrap the singleton row. The IntegrityError recovery handles the
    # rare race where two workers attempt first creation simultaneously.
    try:
        ensure_advertising_shopping_runner_lock()
    except IntegrityError:
        pass

    lease_expires_at = moment + timedelta(
        seconds=lease_seconds,
    )

    updated = (
        AdvertisingShoppingRunnerLock.objects
        .filter(
            key=AdvertisingShoppingRunnerLock.SINGLETON_KEY,
        )
        .filter(
            Q(owner_token__isnull=True) |
            Q(lease_expires_at__isnull=True) |
            Q(lease_expires_at__lte=moment)
        )
        .update(
            owner_token=owner_token,
            acquired_at=moment,
            lease_expires_at=lease_expires_at,
            updated_at=moment,
        )
    )

    lock = AdvertisingShoppingRunnerLock.objects.get(
        key=AdvertisingShoppingRunnerLock.SINGLETON_KEY,
    )

    acquired = (
        updated == 1
        and lock.owner_token == owner_token
    )

    return {
        "acquired": acquired,
        "lock": lock,
        "owner_token": owner_token,
        "lease_expires_at": (
            lease_expires_at
            if acquired
            else lock.lease_expires_at
        ),
    }


def release_advertising_shopping_runner_lock(
    *,
    owner_token,
):
    """
    Release the autonomous shopping lease only when owner_token matches.

    Returns True when this caller released the lease.
    Returns False when the lease was absent or belonged to another worker.
    """
    if owner_token is None:
        return False

    updated = (
        AdvertisingShoppingRunnerLock.objects
        .filter(
            key=AdvertisingShoppingRunnerLock.SINGLETON_KEY,
            owner_token=owner_token,
        )
        .update(
            owner_token=None,
            acquired_at=None,
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
    )

    return updated == 1


def run_guarded_autonomous_advertising_shopping_pass(
    *,
    moment=None,
    lookahead_minutes=60,
    policy=None,
    campaign_limit=None,
    lease_seconds=300,
):
    """
    H3B-4A guarded execution boundary around H3B-3C.

    This is the function future schedulers and management commands should call.

    They should NOT call H3B-3C directly.

    Pipeline:

        scheduler / manual command / future worker
                    ↓
              H3B-4A guard
                    ↓
              acquire lease
               /        \\
          unavailable   acquired
              ↓            ↓
          safe exit      H3B-3C
                           ↓
                    execution ledger
                           ↓
                     release lease

    A lease is always released from a finally block when this process still
    owns it.

    Unexpected H3B-3C exceptions are recorded in the execution ledger and
    then re-raised. Operational callers therefore receive a truthful failure
    while the database retains the audit evidence.
    """
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    moment = moment or timezone.now()

    if (
        isinstance(lookahead_minutes, bool)
        or not isinstance(lookahead_minutes, int)
        or lookahead_minutes <= 0
    ):
        raise ValidationError(
            "Autonomous shopping lookahead must be a positive integer."
        )

    if campaign_limit is not None:
        if (
            isinstance(campaign_limit, bool)
            or not isinstance(campaign_limit, int)
            or campaign_limit <= 0
        ):
            raise ValidationError(
                "Campaign limit must be a positive integer."
            )

    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or lease_seconds <= 0
    ):
        raise ValidationError(
            "Lease seconds must be a positive integer."
        )

    owner_token = uuid.uuid4()

    claim = acquire_advertising_shopping_runner_lock(
        owner_token=owner_token,
        moment=moment,
        lease_seconds=lease_seconds,
    )

    if not claim["acquired"]:
        execution = AdvertisingShoppingExecution.objects.create(
            status=AdvertisingShoppingExecution.STATUS_LOCKED_OUT,
            started_at=moment,
            finished_at=timezone.now(),
            lookahead_minutes=lookahead_minutes,
            campaign_limit=campaign_limit,
            failure_type="runner_lock_unavailable",
            failure_message=(
                "Autonomous advertising shopping pass was not started "
                "because another execution currently owns the runner lease."
            ),
        )

        return {
            "executed": False,
            "reason": "runner_lock_unavailable",
            "execution": execution,
            "runner_result": None,
        }

    execution = AdvertisingShoppingExecution.objects.create(
        execution_id=owner_token,
        status=AdvertisingShoppingExecution.STATUS_RUNNING,
        started_at=moment,
        lease_expires_at=claim["lease_expires_at"],
        lookahead_minutes=lookahead_minutes,
        campaign_limit=campaign_limit,
    )

    try:
        runner_result = run_autonomous_advertising_shopping_pass(
            moment=moment,
            lookahead_minutes=lookahead_minutes,
            policy=policy,
            campaign_limit=campaign_limit,
        )

        execution.status = (
            AdvertisingShoppingExecution.STATUS_COMPLETED
        )
        execution.finished_at = timezone.now()
        execution.processed_count = runner_result["processed_count"]
        execution.purchased_count = runner_result["purchased_count"]
        execution.skipped_count = runner_result["skipped_count"]
        execution.failed_count = runner_result["failed_count"]

        execution.save(
            update_fields=[
                "status",
                "finished_at",
                "processed_count",
                "purchased_count",
                "skipped_count",
                "failed_count",
                "updated_at",
            ]
        )

        return {
            "executed": True,
            "reason": "completed",
            "execution": execution,
            "runner_result": runner_result,
        }

    except Exception as exc:
        execution.status = (
            AdvertisingShoppingExecution.STATUS_FAILED
        )
        execution.finished_at = timezone.now()
        execution.failure_type = exc.__class__.__name__
        execution.failure_message = str(exc)

        execution.save(
            update_fields=[
                "status",
                "finished_at",
                "failure_type",
                "failure_message",
                "updated_at",
            ]
        )

        raise

    finally:
        release_advertising_shopping_runner_lock(
            owner_token=owner_token,
        )


# =====================================================================
# 009-A1 — AUTHORITATIVE PROOF-OF-PLAY RECORDER
# =====================================================================

def record_advertising_appearance_play(
    *,
    appearance_id,
    played_at=None,
):
    """
    Record one COMPLETE advertising appearance as actually played.

    IMPORTANT:
    A reservation is not Proof of Play.
    A purchase is not Proof of Play.

    This operation is the authoritative transition from scheduled
    inventory to verified delivery.

    All six-second reservation rows belonging to the appearance are
    transitioned atomically:

        reserved -> played

    Every row receives the same actual proof-of-play timestamp.

    Safety guarantees:
    - appearance must exist
    - complete appearance must be present
    - sequence must be structurally complete
    - every slot must still be reserved
    - cancelled/missed/mixed-state appearances cannot become played
    - duplicate Proof-of-Play recording is idempotent
    - rows are locked during the transition
    """

    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.utils import timezone

    if not appearance_id:
        raise ValidationError(
            "An advertising appearance ID is required."
        )

    played_at = played_at or timezone.now()

    with transaction.atomic():

        reservations = list(
            AdvertisingPlayoutReservation.objects
            .select_for_update()
            .filter(appearance_id=appearance_id)
            .order_by("sequence_number", "pk")
        )

        if not reservations:
            raise ValidationError(
                "Advertising appearance does not exist."
            )

        expected_slot_count = reservations[0].appearance_slot_count

        if expected_slot_count < 1:
            raise ValidationError(
                "Advertising appearance has an invalid slot count."
            )

        if len(reservations) != expected_slot_count:
            raise ValidationError(
                "Advertising appearance is incomplete and cannot be "
                "recorded as played."
            )

        expected_sequence = list(
            range(1, expected_slot_count + 1)
        )

        actual_sequence = [
            reservation.sequence_number
            for reservation in reservations
        ]

        if actual_sequence != expected_sequence:
            raise ValidationError(
                "Advertising appearance has an invalid slot sequence "
                "and cannot be recorded as played."
            )

        # All rows belonging to an appearance must describe the same
        # complete appearance contract.
        first = reservations[0]

        for reservation in reservations[1:]:
            if (
                reservation.placement != first.placement
                or reservation.creative_id != first.creative_id
                or reservation.campaign_id != first.campaign_id
                or reservation.source_type != first.source_type
                or reservation.appearance_slot_count
                != first.appearance_slot_count
            ):
                raise ValidationError(
                    "Advertising appearance reservation rows do not "
                    "share one consistent playout contract."
                )

        statuses = {
            reservation.status
            for reservation in reservations
        }

        # -------------------------------------------------------------
        # IDEMPOTENCY
        # -------------------------------------------------------------
        if statuses == {
            AdvertisingPlayoutReservation.STATUS_PLAYED
        }:
            timestamps = {
                reservation.played_at
                for reservation in reservations
            }

            if None in timestamps or len(timestamps) != 1:
                raise ValidationError(
                    "Played advertising appearance has inconsistent "
                    "Proof-of-Play timestamps."
                )

            return {
                "recorded": False,
                "reason": "already_played",
                "appearance_id": first.appearance_id,
                "played_at": first.played_at,
                "placement": first.placement,
                "creative": first.creative,
                "campaign": first.campaign,
                "source_type": first.source_type,
                "slot_count": expected_slot_count,
                "reservations": reservations,
            }

        # -------------------------------------------------------------
        # STATE AUTHORIZATION
        # -------------------------------------------------------------
        if statuses != {
            AdvertisingPlayoutReservation.STATUS_RESERVED
        }:
            raise ValidationError(
                "Only a fully reserved advertising appearance may be "
                "recorded as played."
            )

        # -------------------------------------------------------------
        # PROOF OF PLAY
        # -------------------------------------------------------------
        reservation_ids = [
            reservation.pk
            for reservation in reservations
        ]

        updated = (
            AdvertisingPlayoutReservation.objects
            .filter(
                pk__in=reservation_ids,
                status=AdvertisingPlayoutReservation.STATUS_RESERVED,
            )
            .update(
                status=AdvertisingPlayoutReservation.STATUS_PLAYED,
                played_at=played_at,
            )
        )

        if updated != expected_slot_count:
            raise ValidationError(
                "Advertising appearance changed while Proof of Play "
                "was being recorded."
            )

        # Keep the returned objects consistent with database state.
        for reservation in reservations:
            reservation.status = (
                AdvertisingPlayoutReservation.STATUS_PLAYED
            )
            reservation.played_at = played_at

        # 009-B8 — Campaign lifecycle completion is evaluated only after
        # authoritative Proof-of-Play has been fully persisted.
        #
        # Local import intentionally avoids coupling the model module's import
        # graph to the lifecycle service at module import time.
        campaign = first.campaign

        if campaign is not None:
            from ballot.advertising_lifecycle import (
                complete_campaign_if_fully_delivered,
            )

            complete_campaign_if_fully_delivered(campaign)

        return {
            "recorded": True,
            "reason": "played",
            "appearance_id": first.appearance_id,
            "played_at": played_at,
            "placement": first.placement,
            "creative": first.creative,
            "campaign": first.campaign,
            "source_type": first.source_type,
            "slot_count": expected_slot_count,
            "reservations": reservations,
        }
