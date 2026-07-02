from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AssociationMembership,
    AssociationProfile,
    BallotSettings,
    Category,
    NominationCategoryRequest,
    Nominee,
    Vote,
)


@admin.register(BallotSettings)
class BallotSettingsAdmin(admin.ModelAdmin):
    list_display = ("status_label", "paused", "stopped", "start_at", "end_at", "updated_at")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "group", "sort_order", "is_active")
    list_filter = ("group", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("sort_order", "name")


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
    list_filter = ("approval_status", "is_active", "category")
    search_fields = ("name", "contact_email", "category__name")
    readonly_fields = ("photo_preview", "upload_token", "approved_at", "rejected_at", "created_at", "updated_at")
    actions = ("approve_selected_nominees", "reject_selected_nominees", "archive_selected_nominees", "restore_selected_nominees")

    fieldsets = (
        ("Nominee", {
            "fields": (
                "name",
                "category",
                "photo",
                "photo_preview",
                "website",
                "social_link",
                "contact_email",
            )
        }),
        ("Approval", {
            "fields": (
                "approval_status",
                "approved_at",
                "rejected_at",
                "is_active",
            )
        }),
        ("Upload Link", {
            "fields": ("upload_token",)
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    @admin.display(description="Photo")
    def photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="height:60px;width:60px;object-fit:cover;border-radius:8px;" />',
                obj.photo.url,
            )
        return "-"

    @admin.action(description="Approve selected nominees and send approval notice")
    def approve_selected_nominees(self, request, queryset):
        count = 0
        for nominee in queryset:
            nominee.approve()
            count += 1
        self.message_user(request, f"Approved {count} nominee(s). Approval notices were sent when contact emails were available.")

    @admin.action(description="Reject selected nominees")
    def reject_selected_nominees(self, request, queryset):
        count = 0
        for nominee in queryset:
            nominee.reject()
            count += 1
        self.message_user(request, f"Rejected {count} nominee(s).")

    @admin.action(description="Archive selected nominees")
    def archive_selected_nominees(self, request, queryset):
        for nominee in queryset:
            nominee.archive()
        self.message_user(request, f"Archived {queryset.count()} nominee(s).")

    @admin.action(description="Restore selected nominees")
    def restore_selected_nominees(self, request, queryset):
        queryset.update(is_active=True, deleted_at=None)
        self.message_user(request, f"Restored {queryset.count()} nominee(s).")


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("email", "category", "nominee", "created_at", "ip_address")
    list_filter = ("category", "nominee", "created_at")
    search_fields = ("email", "nominee__name", "category__name")
    readonly_fields = ("email", "category", "nominee", "ip_address", "user_agent", "created_at")


@admin.register(AssociationProfile)
class AssociationProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "business_name", "member_level", "notification_email", "member_since")
    list_filter = ("member_level", "member_since")
    search_fields = ("user__username", "user__email", "full_name", "business_name", "notification_email")
    readonly_fields = ("member_since", "updated_at")



@admin.register(AssociationMembership)
class AssociationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "nominee", "is_active", "created_at", "activated_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("user__username", "user__email", "nominee__name")
    actions = ("approve_access",)

    @admin.action(description="Approve selected dashboard access")
    def approve_access(self, request, queryset):
        from django.utils import timezone

        queryset.update(is_active=True, activated_at=timezone.now())
        self.message_user(request, f"Approved {queryset.count()} access request(s).")


@admin.register(NominationCategoryRequest)
class NominationCategoryRequestAdmin(admin.ModelAdmin):
    list_display = ("source_nominee", "target_category", "requester", "status", "created_at", "decided_at")
    list_filter = ("status", "target_category", "created_at")
    search_fields = ("source_nominee__name", "target_category__name", "requester__username")
    readonly_fields = ("created_at", "decided_at")
