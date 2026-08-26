from __future__ import annotations
from .models import AtlsHottestEvent
# ballot/forms.py

from django import forms

from .models import Category, Nominee, AdvertisingInquiry


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


    photo = forms.ImageField()


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
    photo = forms.ImageField(required=False)

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
    class Meta:
        model = AdvertisingInquiry
        fields = [
            "business_name",
            "contact_name",
            "email",
            "phone",
            "website",
            "placement_interest",
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
            "budget_range": forms.TextInput(attrs={"placeholder": "Example: $50-$250, $500+, monthly package"}),
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



class EventSubmissionForm(forms.ModelForm):
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
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 6}),
        }
