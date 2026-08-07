from __future__ import annotations
import secrets

# ballot/models.py

import uuid

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

    photo = models.ImageField(upload_to="nominees/", blank=True, null=True)
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
    social_media = models.URLField(blank=True)
    website = models.URLField(blank=True)
    notification_email = models.EmailField(blank=True)
    profile_pic = models.ImageField(upload_to="association_profiles/", blank=True, null=True)
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
# ATL's Hottest Billboard System
# Powered By The MajesticMall Megaverse Advertising Platform
# =========================================================

class BillboardAd(models.Model):
    PLACEMENT_HOMEPAGE_TOP = "homepage_top"
    PLACEMENT_HOMEPAGE_VIDEO = "homepage_video"
    PLACEMENT_VOTING_TOP = "voting_top"
    PLACEMENT_CATEGORY_TOP = "category_top"
    PLACEMENT_NOMINEE_PROFILE = "nominee_profile"
    PLACEMENT_CONFIRMATION = "confirmation"
    PLACEMENT_ATL_TV = "atl_tv"

    PLACEMENT_CHOICES = [
        (PLACEMENT_HOMEPAGE_TOP, "Homepage Red Carpet Billboard"),
        (PLACEMENT_HOMEPAGE_VIDEO, "Homepage TV Sponsor Billboard"),
        (PLACEMENT_VOTING_TOP, "Voting Page Billboard"),
        (PLACEMENT_CATEGORY_TOP, "Category Sponsor Billboard"),
        (PLACEMENT_NOMINEE_PROFILE, "Nominee Profile Sponsor"),
        (PLACEMENT_CONFIRMATION, "Confirmation Page Billboard"),
        (PLACEMENT_ATL_TV, "ATL TV Sponsor Billboard"),
    ]

    advertiser_name = models.CharField(max_length=160)
    title = models.CharField(max_length=180)
    subtitle = models.CharField(max_length=240, blank=True)
    placement = models.CharField(max_length=40, choices=PLACEMENT_CHOICES, default=PLACEMENT_HOMEPAGE_TOP)
    image = models.ImageField(upload_to="billboards/", blank=True, null=True)
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

class AdvertisingInquiry(models.Model):
    PLACEMENT_HOMEPAGE = "homepage"
    PLACEMENT_VOTING = "voting"
    PLACEMENT_CATEGORY = "category"
    PLACEMENT_NOMINEE = "nominee"
    PLACEMENT_ATL_TV = "atl_tv"
    PLACEMENT_FULL_CAMPAIGN = "full_campaign"

    PLACEMENT_CHOICES = [
        (PLACEMENT_HOMEPAGE, "Homepage Billboard"),
        (PLACEMENT_VOTING, "Voting Page Billboard"),
        (PLACEMENT_CATEGORY, "Category Sponsor"),
        (PLACEMENT_NOMINEE, "Nominee Profile Sponsor"),
        (PLACEMENT_ATL_TV, "ATL TV Sponsor"),
        (PLACEMENT_FULL_CAMPAIGN, "Full ATL’s Hottest Campaign"),
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
        help_text="Optional budget range or campaign spend."
    )
    requested_start_date = models.DateField(blank=True, null=True)
    requested_end_date = models.DateField(blank=True, null=True)
    creative_upload = models.FileField(
        upload_to="advertising_inquiries/",
        blank=True,
        null=True,
        help_text="Optional ad creative, flyer, logo, or campaign artwork."
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Advertising Inquiry"
        verbose_name_plural = "Advertising Inquiries"

    def __str__(self):
        return f"{self.business_name} — {self.get_placement_interest_display()}"
