# ballot/models.py
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
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
        return self.filter(is_active=True)

    def for_ballot(self):
        return self.active().select_related("category").order_by("category__name", "name")


class Nominee(models.Model):
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