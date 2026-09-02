from __future__ import annotations
from .models import AtlsHottestEvent
# ballot/forms.py

from django import forms

from .models import (
    Category,
    Nominee,
    AdvertisingInquiry,
    validate_safe_image_upload,
)


class NomineePhotoForm(forms.Form):
    nominator_name = forms.CharField(
        label="ATL's Hottest Fan (Name of Person Nominating)",
        required=True,
        max_length=160,
        widget=forms.TextInput(attrs={
            "placeholder": "Your name",
            "autocomplete": "name",
        }),
    )
    nominator_email = forms.EmailField(
        label="Valid Email Address",
        required=True,
        widget=forms.EmailInput(attrs={
            "placeholder": "your@email.com",
            "autocomplete": "email",
        }),
    )


    photo = forms.ImageField(
        validators=[validate_safe_image_upload],
        help_text="JPG, PNG, or WEBP only. Maximum 10 MB.",
    )


class NomineeProfileForm(forms.ModelForm):
    class Meta:
        model = Nominee
        fields = ["photo", "website", "social_link", "contact_email"]


class CategoryRequestForm(forms.Form):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    def __init__(self, nominee, *args, **kwargs):
        super().__init__(*args, **kwargs)

        optional_nominee_fields = [
            "nominee_email",
            "nominee_social_media",
            "nominee_social",
            "social_media",
            "instagram",
            "nominee_instagram",
        ]

        for field_name in optional_nominee_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False
                self.fields[field_name].help_text = (
                    "If you know the nominee’s social media or email address, please include it. "
                    "If not, you can still submit the nomination."
                )

        self.nominee = nominee
        self.fields["categories"].queryset = (
            Category.objects.filter(is_active=True)
            .exclude(pk=nominee.category_id)
            .order_by("group", "sort_order", "name")
        )

    def clean_categories(self):
        cats = self.cleaned_data["categories"]
        if cats.count() > 5:
            raise forms.ValidationError("Choose up to 5 categories.")
        return cats


class NomineeSignupForm(forms.Form):
    nominator_name = forms.CharField(
        label="ATL's Hottest Fan (Name of Person Nominating)",
        required=True,
        max_length=160,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your name",
            "autocomplete": "name",
        }),
    )
    nominator_email = forms.EmailField(
        label="Valid Email Address",
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your valid email address",
            "autocomplete": "email",
        }),
    )


    nominee_name = forms.CharField(max_length=160)
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.filter(is_active=True).order_by("group", "sort_order", "name"),
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )
    website = forms.URLField(required=False)
    social_link = forms.URLField(required=False)
    contact_email = forms.EmailField(required=False)
    photo = forms.ImageField(
        required=False,
        validators=[validate_safe_image_upload],
        help_text="JPG, PNG, or WEBP only. Maximum 10 MB.",
    )

    def clean_categories(self):
        cats = self.cleaned_data["categories"]
        if cats.count() > 5:
            raise forms.ValidationError("Choose up to 5 categories.")
        return cats


class AssociationProfileForm(forms.ModelForm):
    class Meta:
        from .models import AssociationProfile

        model = AssociationProfile
        fields = [
            "full_name",
            "business_name",
            "social_media",
            "website",
            "notification_email",
            "profile_pic",
            "special_interest",
        ]
        widgets = {
            "special_interest": forms.Textarea(attrs={"rows": 5}),
        }



class AdvertisingInquiryForm(forms.ModelForm):
    requested_placements = forms.MultipleChoiceField(
        choices=AdvertisingInquiry.PLACEMENT_CHOICES[:-1],
        required=True,
        widget=forms.CheckboxSelectMultiple,
        label="Advertising Properties",
        help_text="Choose one or more ATL’s Hottest advertising properties.",
    )

    total_budget = forms.DecimalField(
        required=True,
        min_value=0,
        decimal_places=2,
        max_digits=10,
        label="Total Campaign Budget",
        widget=forms.NumberInput(attrs={
            "min": "0",
            "step": "0.01",
            "placeholder": "100.00",
        }),
    )

    class Meta:
        model = AdvertisingInquiry
        fields = [
            "business_name",
            "contact_name",
            "email",
            "phone",
            "website",
            "requested_placements",
            "purchase_type",
            "total_budget",
            "budget_range",
            "requested_start_date",
            "requested_end_date",
            "creative_upload",
            "creative_notes",
            "campaign_message",
        ]
        widgets = {
            "business_name": forms.TextInput(attrs={"placeholder": "Business or brand name"}),
            "contact_name": forms.TextInput(attrs={"placeholder": "Your name"}),
            "email": forms.EmailInput(attrs={"placeholder": "best@email.com"}),
            "phone": forms.TextInput(attrs={"placeholder": "Phone number"}),
            "website": forms.URLInput(attrs={"placeholder": "https://yourbrand.com"}),
            "purchase_type": forms.Select(),
            "budget_range": forms.TextInput(attrs={
                "placeholder": "Optional notes about budget, duration, or package"
            }),
            "requested_start_date": forms.DateInput(attrs={"type": "date"}),
            "requested_end_date": forms.DateInput(attrs={"type": "date"}),
            "creative_notes": forms.Textarea(attrs={
                "placeholder": "Tell us about your creative, artwork, logo, copy, sizing, or link instructions.",
                "rows": 4,
            }),
            "campaign_message": forms.Textarea(attrs={
                "placeholder": "Tell us what you want to promote and when you want your campaign to run.",
                "rows": 5,
            }),
        }

    def clean(self):
        from decimal import Decimal

        cleaned = super().clean()

        placements = cleaned.get("requested_placements") or []
        total_budget = cleaned.get("total_budget")
        start_date = cleaned.get("requested_start_date")
        end_date = cleaned.get("requested_end_date")

        if start_date and end_date and end_date < start_date:
            self.add_error(
                "requested_end_date",
                "Requested end date must be on or after the start date.",
            )

        required_minimum = Decimal("0.00")

        # More than one property requires at least $50 total spend.
        if len(placements) > 1:
            required_minimum = max(
                required_minimum,
                Decimal("50.00"),
            )

        # Homepage Red Carpet is premium inventory.
        if AdvertisingInquiry.PLACEMENT_HOMEPAGE in placements:
            required_minimum = max(
                required_minimum,
                Decimal("50.00"),
            )

        if (
            total_budget is not None
            and total_budget < required_minimum
        ):
            self.add_error(
                "total_budget",
                (
                    f"The selected advertising properties require "
                    f"a minimum total campaign budget of "
                    f"${required_minimum:.2f}."
                ),
            )

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)

        placements = self.cleaned_data.get(
            "requested_placements"
        ) or []

        instance.requested_placements = list(placements)

        # Preserve the original single-placement field for
        # compatibility with existing Admin/reporting code.
        if len(placements) == 1:
            instance.placement_interest = placements[0]
        elif len(placements) > 1:
            instance.placement_interest = (
                AdvertisingInquiry.PLACEMENT_FULL_CAMPAIGN
            )

        if commit:
            instance.save()

        return instance



class EventSubmissionForm(forms.ModelForm):
    starts_at = forms.SplitDateTimeField(
        label="Event Begins",
        required=True,
        input_date_formats=["%Y-%m-%d"],
        input_time_formats=["%H:%M"],
        widget=forms.SplitDateTimeWidget(
            date_attrs={
                "type": "date",
                "class": "event-date-input",
                "aria-label": "Event begin date",
                "onclick": "if (this.showPicker) this.showPicker();",
            },
            time_attrs={
                "type": "time",
                "class": "event-time-input",
                "aria-label": "Event begin time",
                "onclick": "if (this.showPicker) this.showPicker();",
            },
        ),
    )

    ends_at = forms.SplitDateTimeField(
        label="Event Ends",
        required=False,
        input_date_formats=["%Y-%m-%d"],
        input_time_formats=["%H:%M"],
        widget=forms.SplitDateTimeWidget(
            date_attrs={
                "type": "date",
                "class": "event-date-input",
                "aria-label": "Event end date",
                "onclick": "if (this.showPicker) this.showPicker();",
            },
            time_attrs={
                "type": "time",
                "class": "event-time-input",
                "aria-label": "Event end time",
                "onclick": "if (this.showPicker) this.showPicker();",
            },
        ),
    )

    class Meta:
        model = AtlsHottestEvent
        fields = [
            "title",
            "category",
            "organizer_name",
            "organizer_email",
            "organizer_phone",
            "venue_name",
            "address",
            "city",
            "state",
            "starts_at",
            "ends_at",
            "description",
            "flyer",
            "ticket_link",
            "website",
        ]
        labels = {
            "title": "Event Title",
            "category": "Event Category",
            "organizer_name": "Organizer Name",
            "organizer_email": "Organizer Email",
            "organizer_phone": "Organizer Phone",
            "venue_name": "Venue Name",
            "starts_at": "Event Begins",
            "ends_at": "Event Ends",
            "description": "Event Description",
            "flyer": "Upload Event Flyer / Promotional Image",
            "ticket_link": "Ticket Link",
            "website": "Event Website",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")

        if starts_at and ends_at and ends_at < starts_at:
            self.add_error("ends_at", "The event end date/time cannot be before the begin date/time.")

        return cleaned_data
