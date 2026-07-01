# ballot/admin.py
from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import (
    AssociationMembership,
    BallotSettings,
    Category,
    NominationCategoryRequest,
    Nominee,
    Vote,
)
from .services import approve_category_request, deny_category_request


@admin.register(BallotSettings)
class BallotSettingsAdmin(admin.ModelAdmin):
    list_display = ("status_badge", "start_at", "end_at", "paused", "stopped", "updated_at")
    readonly_fields = ("status_badge", "updated_at")
    fieldsets = (
        ("Current Status", {"fields": ("status_badge",)}),
        ("Schedule", {"fields": ("start_at", "end_at")}),
        ("Controls", {"fields": ("paused", "stopped", "announcement")}),
        ("Meta", {"fields": ("updated_at",)}),
    )
    actions = ("pause_voting", "resume_voting", "stop_voting")

    def has_add_permission(self, request):
        return not BallotSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def status_badge(self, obj):
        label = obj.status_label()
        colors = {
            "active": "#157347",
            "scheduled": "#0d6efd",
            "paused": "#fd7e14",
            "ended": "#6c757d",
            "stopped": "#dc3545",
        }
        return format_html(
            '<span style="padding:3px 10px;border-radius:999px;background:{};color:white;font-weight:700;">{}</span>',
            colors.get(label, "#6c757d"),
            label.title(),
        )

    status_badge.short_description = "Current Status"

    @admin.action(description="Pause voting")
    def pause_voting(self, request, queryset):
        s = BallotSettings.get_solo()
        s.paused = True
        s.stopped = False
        s.save()
        self.message_user(request, "Voting paused.", messages.SUCCESS)

    @admin.action(description="Resume voting")
    def resume_voting(self, request, queryset):
        s = BallotSettings.get_solo()
        s.paused = False
        s.stopped = False
        s.save()
        self.message_user(request, "Voting resumed.", messages.SUCCESS)

    @admin.action(description="Stop voting")
    def stop_voting(self, request, queryset):
        s = BallotSettings.get_solo()
        s.stopped = True
        s.save()
        self.message_user(request, "Voting stopped.", messages.SUCCESS)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "group", "sort_order", "is_active", "nominee_count")
    list_editable = ("group", "sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")
    list_filter = ("group", "is_active")

    def nominee_count(self, obj):
        return obj.nominees.count()

    nominee_count.short_description = "Nominees"


@admin.register(Nominee)
class NomineeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "approval_status",
        "is_active",
        "contact_email",
        "photo_preview",
        "created_at",
    )
    list_filter = ("approval_status", "category", "is_active")
    search_fields = ("name", "contact_email", "website", "social_link")
    readonly_fields = (
        "upload_token",
        "created_at",
        "updated_at",
        "photo_preview",
        "approved_at",
        "rejected_at",
    )
    actions = ("approve_nominees", "reject_nominees", "archive_nominees", "restore_nominees")

    fieldsets = (
        ("Nominee", {"fields": ("name", "category", "approval_status", "is_active")}),
        ("Photo", {"fields": ("photo", "photo_preview", "photo_submitted_at")}),
        ("Contact / Links", {"fields": ("website", "social_link", "contact_email")}),
        ("Upload Link", {"fields": ("upload_token",)}),
        ("Decision Times", {"fields": ("approved_at", "rejected_at")}),
        ("Meta", {"fields": ("created_at", "updated_at", "deleted_at")}),
    )

    def photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="width:54px;height:54px;object-fit:contain;background:#111;border-radius:6px;">',
                obj.photo.url,
            )
        return "-"

    photo_preview.short_description = "Photo"

    @admin.action(description="Approve selected nominees")
    def approve_nominees(self, request, queryset):
        count = 0
        for nominee in queryset:
            nominee.approve()
            count += 1
        self.message_user(request, f"Approved {count} nominee(s).", messages.SUCCESS)

    @admin.action(description="Reject selected nominees")
    def reject_nominees(self, request, queryset):
        count = 0
        for nominee in queryset:
            nominee.reject()
            count += 1
        self.message_user(request, f"Rejected {count} nominee(s).", messages.WARNING)

    @admin.action(description="Archive selected nominees")
    def archive_nominees(self, request, queryset):
        count = 0
        for nominee in queryset:
            nominee.archive()
            count += 1
        self.message_user(request, f"Archived {count} nominee(s).", messages.SUCCESS)

    @admin.action(description="Restore selected nominees")
    def restore_nominees(self, request, queryset):
        count = queryset.update(is_active=True, deleted_at=None)
        self.message_user(request, f"Restored {count} nominee(s).", messages.SUCCESS)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("email", "category", "nominee", "created_at", "ip_address")
    list_filter = ("category", "nominee")
    search_fields = ("email", "nominee__name", "category__name")
    readonly_fields = ("created_at",)


@admin.register(AssociationMembership)
class AssociationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "nominee", "is_active", "created_at", "activated_at")
    list_filter = ("is_active", "nominee__category")
    search_fields = ("user__username", "user__email", "nominee__name")
    list_editable = ("is_active",)
    actions = ("approve_memberships", "revoke_memberships")

    @admin.action(description="Approve selected memberships")
    def approve_memberships(self, request, queryset):
        count = 0
        for membership in queryset:
            membership.is_active = True
            membership.save()
            count += 1
        self.message_user(request, f"Approved {count} membership(s).", messages.SUCCESS)

    @admin.action(description="Revoke selected memberships")
    def revoke_memberships(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Revoked {count} membership(s).", messages.SUCCESS)


@admin.register(NominationCategoryRequest)
class NominationCategoryRequestAdmin(admin.ModelAdmin):
    list_display = ("source_nominee", "target_category", "requester", "status", "created_at", "decided_at")
    list_filter = ("status", "target_category")
    search_fields = (
        "source_nominee__name",
        "target_category__name",
        "requester__username",
        "requester__email",
    )
    actions = ("approve_requests", "deny_requests")

    @admin.action(description="Approve selected category requests")
    def approve_requests(self, request, queryset):
        count = 0
        for req in queryset:
            if req.status == NominationCategoryRequest.STATUS_PENDING:
                approve_category_request(req)
                count += 1
        self.message_user(request, f"Approved {count} request(s).", messages.SUCCESS)

    @admin.action(description="Deny selected category requests")
    def deny_requests(self, request, queryset):
        count = 0
        for req in queryset:
            if req.status == NominationCategoryRequest.STATUS_PENDING:
                deny_category_request(req)
                count += 1
        self.message_user(request, f"Denied {count} request(s).", messages.SUCCESS)
