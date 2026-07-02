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

    def send_approval_notice(self):
        if not self.contact_email:
            return

        UserModel = get_user_model()
        email = self.contact_email.strip().lower()

        base_username = email.split("@")[0].replace(".", "_").replace("-", "_") or f"nominee_{self.pk}"
        username = base_username[:120]
        counter = 2

        user = UserModel.objects.filter(email__iexact=email).first()
        temporary_password = None
        created = False

        if user is None:
            candidate = username
            while UserModel.objects.filter(username=candidate).exists():
                suffix = f"_{counter}"
                candidate = f"{username[:120-len(suffix)]}{suffix}"
                counter += 1

            temporary_password = secrets.token_urlsafe(10)
            user = UserModel.objects.create_user(
                username=candidate,
                email=email,
                password=temporary_password,
            )
            created = True

        membership, _created_membership = AssociationMembership.objects.get_or_create(
            user=user,
            nominee=self,
            defaults={"is_active": True, "activated_at": timezone.now()},
        )

        if not membership.is_active:
            membership.is_active = True
            membership.activated_at = timezone.now()
            membership.save(update_fields=["is_active", "activated_at"])

        login_url = "/accounts/login/"
        dashboard_url = "/association/dashboard/"

        if created:
            login_lines = [
                f"Username: {user.username}",
                f"Temporary password: {temporary_password}",
                "",
                "Please log in and complete your nominee dashboard profile.",
            ]
            login_html = f"""
              <p><strong>Username:</strong> {user.username}</p>
              <p><strong>Temporary password:</strong> {temporary_password}</p>
              <p>Please log in and complete your nominee dashboard profile.</p>
            """
        else:
            login_lines = [
                f"Username: {user.username}",
                "",
                "An account already exists for this email. Please log in with your existing password.",
            ]
            login_html = f"""
              <p><strong>Username:</strong> {user.username}</p>
              <p>An account already exists for this email. Please log in with your existing password.</p>
            """

        text_message = "\n".join(
            [
                "Congratulations!",
                "",
                f"{self.name} has been approved for:",
                self.category.name,
                "",
                "What to do next:",
                "1. Log in to the approved nominee dashboard.",
                "2. Complete your nominee profile.",
                "3. Add/update your photo, website, social link, and contact details.",
                "4. Get ready for the official voting period.",
                "",
                *login_lines,
                "",
                f"Login page: {login_url}",
                f"Dashboard: {dashboard_url}",
                "",
                "ATL's Hottest Awards Association",
            ]
        )

        html_message = f"""
        <div style="margin:0;padding:0;background:#050505;color:#ffffff;font-family:Georgia,serif;">
          <div style="max-width:700px;margin:0 auto;padding:28px;">
            <div style="border:1px solid #ffd76a;border-radius:24px;overflow:hidden;background:linear-gradient(135deg,#000000,#650310);box-shadow:0 0 28px rgba(255,215,106,0.22);">
              <div style="padding:28px;border-bottom:1px solid rgba(255,215,106,0.55);background:linear-gradient(135deg,#000,#7d0616,#000);">
                <p style="margin:0 0 8px;color:#ffd76a;text-transform:uppercase;letter-spacing:3px;font-weight:bold;">Approved Nomination Notice</p>
                <h1 style="margin:0;color:#fff;font-size:34px;line-height:1.05;">Congratulations!</h1>
              </div>

              <div style="padding:28px;">
                <p style="font-size:18px;line-height:1.6;">
                  <strong>{self.name}</strong> has been approved for:
                </p>

                <div style="margin:18px 0;padding:16px;border:1px solid rgba(255,215,106,0.55);border-radius:16px;background:rgba(0,0,0,0.35);">
                  <p style="margin:0;color:#ffd76a;font-size:20px;font-weight:bold;">{self.category.name}</p>
                </div>

                <h2 style="color:#ffd76a;">What to do next</h2>
                <ol style="line-height:1.8;">
                  <li>Log in to the approved nominee dashboard.</li>
                  <li>Complete your nominee profile.</li>
                  <li>Add/update your photo, website, social link, and contact details.</li>
                  <li>Get ready for the official voting period.</li>
                </ol>

                <div style="margin:20px 0;padding:16px;border:1px solid rgba(215,25,53,0.65);border-radius:16px;background:rgba(215,25,53,0.15);">
                  {login_html}
                </div>

                <p>
                  <strong>Login:</strong> {login_url}<br>
                  <strong>Dashboard:</strong> {dashboard_url}
                </p>

                <p style="color:#ffd76a;font-weight:bold;">ATL's Hottest Awards Association</p>
              </div>
            </div>
          </div>
        </div>
        """

        try:
            msg = EmailMultiAlternatives(
                subject=f"Approved: {self.name} for {self.category.name}",
                body=text_message,
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send(fail_silently=True)
        except Exception:
            pass

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
