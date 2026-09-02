from __future__ import annotations
import secrets

# ballot/models.py

import uuid
import warnings
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
    def for_ballot(self):
        return (
            self.filter(is_active=True)
            .order_by("group", "sort_order", "name")
            .prefetch_related(
                models.Prefetch(
                    "nominees",
                    queryset=Nominee.objects.filter(is_active=True).order_by("name"),
                    to_attr="prefetched_nominees",
                )
            )
        )


class Category(models.Model):
    GROUP_CHOICES = (
        ("general", "General"),
        ("music", "Music"),
        ("business", "Business"),
        ("community", "Community"),
        ("entertainment", "Entertainment"),
        ("food", "Food"),
        ("sports", "Sports"),
        ("beauty", "Beauty"),
        ("fashion", "Fashion"),
        ("media", "Media"),
    )

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    group = models.CharField(max_length=40, choices=GROUP_CHOICES, default="general")
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
                fields=["name", "category"],
                name="unique_nominee_name_per_category",
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

    def send_approval_email(self, user, temporary_password=None):
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
            categories=[self.category.name] if self.category else [],
            login_url=absolute_url("/accounts/login/"),
            dashboard_url=absolute_url("/association/dashboard/"),
            nominee_url=nominee_url,
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
        )

        return user

    def archive(self):
        self.is_active = False
        if not self.deleted_at:
            self.deleted_at = timezone.now()
        self.save(update_fields=["is_active", "deleted_at", "updated_at"])


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
                fields=["email", "category"],
                name="one_vote_per_email_per_category",
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

    created_at = models.DateTimeField(auto_now_add=True)

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

