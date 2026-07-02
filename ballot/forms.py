# ballot/forms.py
from __future__ import annotations

from django import forms

from .models import Category, Nominee


class NomineePhotoForm(forms.Form):
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
