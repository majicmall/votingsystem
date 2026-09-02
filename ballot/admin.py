from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AtlsHottestEvent,
    EventPromotionOrder,
    EventPromotionRate,
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


# =========================================================
# ATL's Hottest Billboard System Admin
# Powered By The MajesticMall Megaverse Advertising Platform
# =========================================================

from .models import BillboardAd, AdvertisingInquiry, AdvertisingCampaign, BillboardAdEvent
from .models import MembershipPlan, MembershipBenefit, MembershipReward, UserMembership

@admin.action(
    description="Activate selected advertising campaign(s)"
)
def activate_advertising_campaigns(modeladmin, request, queryset):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.db import transaction

    activated = 0
    skipped = 0

    for campaign in queryset:
        campaign.status = AdvertisingCampaign.STATUS_ACTIVE

        try:
            # Validate campaign budget/minimum rules first.
            campaign.full_clean()

            # Validate every billboard before activating any.
            ads = list(campaign.billboard_ads.all())

            if not ads:
                skipped += 1
                continue

            for ad in ads:
                ad.is_active = True
                ad.full_clean()

            with transaction.atomic():
                campaign.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                for ad in ads:
                    ad.save(
                        update_fields=[
                            "is_active",
                            "updated_at",
                        ]
                    )

            activated += 1

        except ValidationError:
            skipped += 1

    if activated:
        messages.success(
            request,
            (
                f"{activated} advertising campaign(s) "
                f"activated successfully."
            ),
        )

    if skipped:
        messages.warning(
            request,
            (
                f"{skipped} campaign(s) were not activated. "
                f"Review budget, minimum spend, schedule, "
                f"exclusive inventory, and billboard bookings."
            ),
        )


@admin.action(
    description="Pause selected advertising campaign(s)"
)
def pause_advertising_campaigns(modeladmin, request, queryset):
    from django.contrib import messages
    from django.db import transaction

    paused = 0

    for campaign in queryset:
        with transaction.atomic():
            campaign.status = AdvertisingCampaign.STATUS_PAUSED
            campaign.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            campaign.billboard_ads.update(
                is_active=False
            )

        paused += 1

    if paused:
        messages.success(
            request,
            f"{paused} advertising campaign(s) paused.",
        )


@admin.register(AdvertisingCampaign)
class AdvertisingCampaignAdmin(admin.ModelAdmin):
    list_display = (
        "campaign_name",
        "advertiser_name",
        "total_budget",
        "allocated_total_display",
        "remaining_budget_display",
        "status",
        "starts_at",
        "ends_at",
    )
    list_filter = ("status", "starts_at", "ends_at")
    search_fields = (
        "campaign_name",
        "advertiser_name",
        "contact_name",
        "email",
        "phone",
    )
    ordering = ("-created_at",)
    actions = (
        activate_advertising_campaigns,
        pause_advertising_campaigns,
    )
    readonly_fields = (
        "allocated_total_display",
        "remaining_budget_display",
        "required_minimum_spend_display",
        "budget_status_display",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Campaign", {
            "fields": (
                "campaign_name",
                "advertiser_name",
                "status",
            )
        }),
        ("Contact", {
            "fields": (
                "contact_name",
                "email",
                "phone",
            )
        }),
        ("Budget", {
            "fields": (
                "total_budget",
                "minimum_campaign_spend",
                "allocated_total_display",
                "remaining_budget_display",
                "required_minimum_spend_display",
                "budget_status_display",
            )
        }),
        ("Schedule", {
            "fields": (
                "starts_at",
                "ends_at",
            )
        }),
        ("Internal", {
            "fields": (
                "internal_notes",
                "created_at",
                "updated_at",
            )
        }),
    )

    @admin.display(description="Allocated")
    def allocated_total_display(self, obj):
        return obj.allocated_total

    @admin.display(description="Remaining")
    def remaining_budget_display(self, obj):
        return obj.remaining_budget

    @admin.display(description="Required Minimum")
    def required_minimum_spend_display(self, obj):
        return obj.required_minimum_spend

    @admin.display(description="Budget Status")
    def budget_status_display(self, obj):
        return "VALID" if obj.budget_is_valid else "REVIEW REQUIRED"


@admin.register(BillboardAdEvent)
class BillboardAdEventAdmin(admin.ModelAdmin):
    list_display = (
        "ad",
        "event_type",
        "placement",
        "created_at",
    )
    list_filter = (
        "event_type",
        "placement",
        "created_at",
    )
    search_fields = (
        "ad__title",
        "ad__advertiser_name",
    )
    readonly_fields = (
        "ad",
        "event_type",
        "placement",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BillboardAd)
class BillboardAdAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "advertiser_name",
        "placement",
        "campaign",
        "purchase_type",
        "allocated_budget",
        "minimum_spend",
        "is_premium_property",
        "rotation_weight",
        "is_active",
        "starts_at",
        "ends_at",
        "priority",
    )
    list_filter = (
        "placement",
        "purchase_type",
        "is_premium_property",
        "is_active",
        "starts_at",
        "ends_at",
    )
    search_fields = ("title", "advertiser_name", "subtitle", "destination_url")
    ordering = ("priority", "-created_at")
    fieldsets = (
        ("Advertiser", {
            "fields": ("campaign", "advertiser_name", "title", "subtitle")
        }),
        ("Placement & Inventory", {
            "fields": (
                "placement",
                "purchase_type",
                "priority",
                "rotation_weight",
                "is_premium_property",
                "minimum_spend",
                "is_active",
            )
        }),
        ("Campaign Budget", {
            "fields": (
                "campaign_budget",
                "allocated_budget",
            )
        }),
        ("Creative", {
            "fields": ("image", "destination_url", "call_to_action")
        }),
        ("Schedule", {
            "fields": ("starts_at", "ends_at")
        }),
        ("Internal Notes", {
            "fields": ("impressions_note",)
        }),
    )


@admin.action(
    description="Create advertising campaign from selected inquiry/inquiries"
)
def create_campaign_from_inquiry(modeladmin, request, queryset):
    from datetime import datetime, time
    from decimal import Decimal, ROUND_DOWN

    from django.contrib import messages
    from django.db import transaction
    from django.utils import timezone

    created_count = 0
    skipped_count = 0

    placement_labels = dict(BillboardAd.PLACEMENT_CHOICES)

    for inquiry in queryset:
        # -------------------------------------------------
        # Do not duplicate already-converted inquiries.
        # -------------------------------------------------
        if inquiry.converted_campaign_id:
            skipped_count += 1
            continue

        placements = list(
            dict.fromkeys(
                inquiry.requested_placements or []
            )
        )

        # Legacy inquiry fallback.
        if (
            not placements
            and inquiry.placement_interest
            and inquiry.placement_interest
            != AdvertisingInquiry.PLACEMENT_FULL_CAMPAIGN
        ):
            placements = [
                inquiry.placement_interest
            ]

        placements = [
            placement
            for placement in placements
            if placement in placement_labels
        ]

        if not placements or inquiry.total_budget is None:
            skipped_count += 1
            continue

        total_budget = Decimal(inquiry.total_budget)

        # -------------------------------------------------
        # Campaign minimum
        # -------------------------------------------------
        required_minimum = Decimal("0.00")

        if len(placements) > 1:
            required_minimum = Decimal("50.00")

        if (
            AdvertisingInquiry.PLACEMENT_HOMEPAGE
            in placements
        ):
            required_minimum = max(
                required_minimum,
                Decimal("50.00"),
            )

        if total_budget < required_minimum:
            skipped_count += 1
            continue

        # -------------------------------------------------
        # Convert requested dates into campaign datetimes.
        # -------------------------------------------------
        starts_at = None
        ends_at = None

        if inquiry.requested_start_date:
            starts_at = timezone.make_aware(
                datetime.combine(
                    inquiry.requested_start_date,
                    time.min,
                ),
                timezone.get_current_timezone(),
            )

        if inquiry.requested_end_date:
            ends_at = timezone.make_aware(
                datetime.combine(
                    inquiry.requested_end_date,
                    time.max,
                ),
                timezone.get_current_timezone(),
            )

        # -------------------------------------------------
        # Equal initial budget allocation.
        #
        # Staff can modify allocations in Admin before
        # activating the campaign.
        # -------------------------------------------------
        property_count = len(placements)

        equal_share = (
            total_budget / Decimal(property_count)
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        remaining = total_budget

        try:
            with transaction.atomic():
                campaign = AdvertisingCampaign.objects.create(
                    advertiser_name=inquiry.business_name,
                    campaign_name=(
                        f"{inquiry.business_name} "
                        f"Campaign #{inquiry.pk}"
                    ),
                    contact_name=inquiry.contact_name,
                    email=inquiry.email,
                    phone=inquiry.phone,
                    total_budget=total_budget,
                    minimum_campaign_spend=required_minimum,
                    status=AdvertisingCampaign.STATUS_PENDING,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    internal_notes=(
                        f"Created from Advertising Inquiry "
                        f"#{inquiry.pk}. "
                        f"{inquiry.internal_notes}".strip()
                    ),
                )

                for index, placement in enumerate(
                    placements,
                    start=1,
                ):
                    # Give the final property any leftover
                    # pennies so allocations total exactly.
                    if index == property_count:
                        allocated = remaining
                    else:
                        allocated = equal_share
                        remaining -= allocated

                    BillboardAd.objects.create(
                        campaign=campaign,
                        advertiser_name=inquiry.business_name,
                        title=(
                            f"{inquiry.business_name} — "
                            f"{placement_labels[placement]}"
                        ),
                        subtitle="",
                        placement=placement,
                        purchase_type=inquiry.purchase_type,
                        destination_url=inquiry.website or "",
                        call_to_action="Learn More",

                        # Staff approval is still required.
                        is_active=False,

                        starts_at=starts_at,
                        ends_at=ends_at,

                        priority=100,
                        rotation_weight=1,

                        campaign_budget=total_budget,
                        allocated_budget=allocated,

                        minimum_spend=Decimal("0.00"),

                        is_premium_property=(
                            placement
                            == BillboardAd.PLACEMENT_HOMEPAGE_TOP
                        ),

                        impressions_note=(
                            f"Created from Advertising Inquiry "
                            f"#{inquiry.pk}. "
                            f"Review creative, allocation, schedule, "
                            f"and destination before activation."
                        ),
                    )

                inquiry.converted_campaign = campaign
                inquiry.converted_at = timezone.now()
                inquiry.is_contacted = True

                inquiry.save(
                    update_fields=[
                        "converted_campaign",
                        "converted_at",
                        "is_contacted",
                    ]
                )

                created_count += 1

        except Exception:
            skipped_count += 1

    if created_count:
        messages.success(
            request,
            (
                f"{created_count} advertising campaign"
                f"{'' if created_count == 1 else 's'} "
                f"created successfully. Billboard bookings "
                f"were created INACTIVE for final staff review."
            ),
        )

    if skipped_count:
        messages.warning(
            request,
            (
                f"{skipped_count} inquiry/inquiries were skipped. "
                f"They may already be converted or may not contain "
                f"a valid campaign budget/property selection."
            ),
        )


@admin.register(AdvertisingInquiry)
class AdvertisingInquiryAdmin(admin.ModelAdmin):
    list_display = (
        "business_name",
        "contact_name",
        "email",
        "placement_interest",
        "budget_range",
        "requested_start_date",
        "requested_end_date",
        "is_contacted",
        "converted_campaign",
        "converted_at",
        "created_at",
    )
    list_filter = ("placement_interest", "is_contacted", "created_at")
    search_fields = ("business_name", "contact_name", "email", "phone", "website", "campaign_message")
    readonly_fields = (
        "converted_campaign",
        "converted_at",
        "created_at",
    )
    actions = (
        create_campaign_from_inquiry,
    )
    ordering = ("-created_at",)
    fieldsets = (
        ("Advertiser", {
            "fields": ("business_name", "contact_name", "email", "phone", "website")
        }),
        ("Campaign Interest", {
            "fields": (
                "placement_interest",
                "budget_range",
                "requested_start_date",
                "requested_end_date",
                "campaign_message",
            )
        }),
        ("Creative", {
            "fields": ("creative_upload", "creative_notes")
        }),
        ("Campaign Conversion", {
            "fields": (
                "converted_campaign",
                "converted_at",
            )
        }),
        ("Follow Up", {
            "fields": (
                "is_contacted",
                "internal_notes",
                "created_at",
            )
        }),
    )



# =========================================================
# ATL'S HOTTEST AUTOPILOT MEMBERSHIP ADMIN
# =========================================================

class MembershipBenefitInline(admin.TabularInline):
    model = MembershipBenefit
    extra = 1


class MembershipRewardInline(admin.TabularInline):
    model = MembershipReward
    extra = 1


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "price",
        "billing_period",
        "is_featured",
        "is_active",
        "display_order",
    )
    list_filter = ("billing_period", "is_featured", "is_active")
    search_fields = ("name", "tagline", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipBenefitInline, MembershipRewardInline]


@admin.register(MembershipBenefit)
class MembershipBenefitAdmin(admin.ModelAdmin):
    list_display = ("title", "plan", "is_highlighted", "display_order")
    list_filter = ("plan", "is_highlighted")
    search_fields = ("title", "description")


@admin.register(MembershipReward)
class MembershipRewardAdmin(admin.ModelAdmin):
    list_display = ("title", "plan", "reward_type", "value", "is_active", "display_order")
    list_filter = ("plan", "reward_type", "is_active")
    search_fields = ("title", "description", "value")


@admin.register(UserMembership)
class UserMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "auto_renew", "started_at", "expires_at", "updated_at")
    list_filter = ("plan", "status", "auto_renew")
    search_fields = ("user__username", "user__email", "plan__name", "payment_reference")


# =========================================================
# VOTING CAMPAIGN ADMIN CONTROL
# =========================================================

from .models import VotingCampaign


@admin.action(description="Open voting for selected campaign(s)")
def open_voting(modeladmin, request, queryset):
    queryset.update(voting_enabled=True)


@admin.action(description="Close voting for selected campaign(s)")
def close_voting(modeladmin, request, queryset):
    queryset.update(voting_enabled=False)


@admin.action(description="Mark selected campaign as active")
def mark_campaign_active(modeladmin, request, queryset):
    VotingCampaign.objects.update(is_active_campaign=False)
    queryset.update(is_active_campaign=True)


@admin.register(VotingCampaign)
class VotingCampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "voting_status_label",
        "nominations_enabled",
        "voting_enabled",
        "campaign_start_date",
        "campaign_end_date",
        "is_active_campaign",
        "updated_at",
    )
    list_filter = (
        "voting_enabled",
        "nominations_enabled",
        "is_active_campaign",
    )
    search_fields = ("name", "slug", "public_message")
    prepopulated_fields = {"slug": ("name",)}
    actions = [open_voting, close_voting, mark_campaign_active]

    fieldsets = (
        ("Campaign", {
            "fields": (
                "name",
                "slug",
                "is_active_campaign",
                "public_message",
            )
        }),
        ("Nomination Control", {
            "fields": (
                "nominations_enabled",
            )
        }),
        ("Voting Control", {
            "fields": (
                "voting_enabled",
                "campaign_start_date",
                "campaign_end_date",
            )
        }),
    )



@admin.register(AtlsHottestEvent)
class AtlsHottestEventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "starts_at",
        "status",
        "is_featured",
        "show_today",
        "show_on_homepage",
        "homepage_payment_status",
        "homepage_package",
        "homepage_amount_paid",
        "homepage_promotion_start",
        "homepage_promotion_end",
        "submitted_at",
    )

    list_filter = (
        "status",
        "category",
        "is_featured",
        "show_today",
        "show_on_homepage",
        "homepage_payment_status",
        "homepage_package",
        "starts_at",
    )

    search_fields = (
        "title",
        "organizer_name",
        "organizer_email",
        "venue_name",
        "city",
    )

    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("submitted_at", "updated_at")

    fieldsets = (
        ("Event", {
            "fields": (
                "title",
                "slug",
                "category",
                "description",
                "flyer",
            )
        }),
        ("Organizer", {
            "fields": (
                "organizer_name",
                "organizer_email",
                "organizer_phone",
            )
        }),
        ("Location & Schedule", {
            "fields": (
                "venue_name",
                "address",
                "city",
                "state",
                "starts_at",
                "ends_at",
                "ticket_link",
                "website",
            )
        }),
        ("Approval & Event Placement", {
            "fields": (
                "status",
                "is_featured",
                "show_today",
            )
        }),
        ("Premium Homepage Promotion", {
            "fields": (
                "show_on_homepage",
                "homepage_payment_status",
                "homepage_package",
                "homepage_amount_paid",
                "homepage_promotion_start",
                "homepage_promotion_end",
            )
        }),
        ("System", {
            "fields": (
                "submitted_at",
                "updated_at",
            )
        }),
    )


@admin.register(EventPromotionOrder)
class EventPromotionOrderAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "producer_name",
        "producer_email",
        "package",
        "status",
        "quoted_amount",
        "requested_start",
        "requested_end",
        "created_at",
    )

    list_filter = (
        "status",
        "package",
        "created_at",
    )

    search_fields = (
        "event__title",
        "producer_name",
        "producer_email",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "-created_at",
    )

    fieldsets = (
        (
            "Event & Producer",
            {
                "fields": (
                    "event",
                    "producer_name",
                    "producer_email",
                )
            },
        ),
        (
            "Promotion Package",
            {
                "fields": (
                    "package",
                    "requested_start",
                    "requested_end",
                    "quoted_amount",
                    "is_complimentary",
                    "status",
                )
            },
        ),
        (
            "Producer Notes",
            {
                "fields": (
                    "notes",
                )
            },
        ),
        (
            "Order History",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(EventPromotionRate)
class EventPromotionRateAdmin(admin.ModelAdmin):
    list_display = (
        "package",
        "amount",
        "is_active",
        "display_order",
        "updated_at",
    )

    list_editable = (
        "amount",
        "is_active",
        "display_order",
    )

    ordering = ("display_order",)

