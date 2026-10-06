import shutil
import tempfile
from io import BytesIO

from PIL import Image
from django.contrib import admin, messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ballot.admin import SelfNominationCheckInAdmin
from ballot.forms import SelfNominationCheckInForm
from ballot.models import Category, Nominee, SelfNominationCheckIn, VotingCampaign


class SelfNominationCheckInFormTests(TestCase):
    def setUp(self):
        self.categories = [
            Category.objects.create(
                name=f"Check-In Test Category {index}",
                is_active=True,
            )
            for index in range(1, 7)
        ]

    def base_data(self):
        return {
            "name": "ATL Check-In Test",
            "email": "checkin-test@example.com",
            "phone": "",
            "website": "",
            "social_link": "https://instagram.com/example",
            "categories": [str(self.categories[0].pk)],
        }

    def test_phone_photo_website_and_social_are_individually_optional(self):
        form = SelfNominationCheckInForm()

        self.assertFalse(form.fields["phone"].required)
        self.assertFalse(form.fields["photo"].required)
        self.assertFalse(form.fields["website"].required)
        self.assertFalse(form.fields["social_link"].required)
        self.assertTrue(form.fields["categories"].required)

    def test_requires_social_or_website(self):
        data = self.base_data()
        data["social_link"] = ""

        form = SelfNominationCheckInForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("website", form.errors)
        self.assertIn("social_link", form.errors)

    def test_social_alone_is_valid(self):
        form = SelfNominationCheckInForm(data=self.base_data())

        self.assertTrue(form.is_valid(), form.errors.as_text())

    def test_website_alone_is_valid(self):
        data = self.base_data()
        data["social_link"] = ""
        data["website"] = "https://example.com"

        form = SelfNominationCheckInForm(data=data)

        self.assertTrue(form.is_valid(), form.errors.as_text())

    def test_one_to_five_categories_are_allowed(self):
        for count in range(1, 6):
            data = self.base_data()
            data["categories"] = [
                str(category.pk)
                for category in self.categories[:count]
            ]

            form = SelfNominationCheckInForm(data=data)

            self.assertTrue(
                form.is_valid(),
                f"{count} categories should be valid: {form.errors.as_text()}",
            )

    def test_six_categories_are_rejected(self):
        data = self.base_data()
        data["categories"] = [
            str(category.pk)
            for category in self.categories
        ]

        form = SelfNominationCheckInForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("categories", form.errors)
        self.assertIn("Choose up to 5 categories.", form.errors["categories"])



@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SelfNominationCheckInSubmissionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings["MEDIA_ROOT"]
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.category = Category.objects.create(
            name="Check-In Submission Test Category",
            is_active=True,
        )

    def test_submission_saves_pending_checkin_phone_photo_and_category(self):
        image_buffer = BytesIO()
        Image.new("RGB", (10, 10)).save(image_buffer, format="PNG")

        photo = SimpleUploadedFile(
            "checkin-test.png",
            image_buffer.getvalue(),
            content_type="image/png",
        )

        response = self.client.post(
            reverse("self_nomination_checkin"),
            {
                "name": "ATL Upload Test",
                "email": "upload-test@example.com",
                "phone": "404-555-0100",
                "website": "",
                "social_link": "https://instagram.com/example",
                "categories": [str(self.category.pk)],
                "photo": photo,
            },
        )

        self.assertEqual(response.status_code, 302)

        checkin = SelfNominationCheckIn.objects.get(
            email="upload-test@example.com"
        )

        self.assertEqual(
            checkin.status,
            SelfNominationCheckIn.STATUS_PENDING,
        )
        self.assertEqual(checkin.phone, "404-555-0100")
        self.assertTrue(checkin.photo.name.startswith("checkins/"))
        self.assertEqual(
            list(checkin.categories.values_list("pk", flat=True)),
            [self.category.pk],
        )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SelfNominationCheckInApprovalTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings["MEDIA_ROOT"]
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.campaign = VotingCampaign.objects.create(
            name="Check-In Approval Test Campaign",
            slug="checkin-approval-test",
            nominations_enabled=False,
            voting_enabled=False,
            is_active_campaign=True,
        )
        self.categories = [
            Category.objects.create(
                name=f"Approval Test Category {index}",
                is_active=True,
            )
            for index in range(1, 3)
        ]
        self.checkin = SelfNominationCheckIn.objects.create(
            name="ATL Approval Test",
            email="approval-test@example.com",
            phone="404-555-0199",
            website="",
            social_link="https://instagram.com/approvaltest",
        )
        self.checkin.categories.set(self.categories)

    def test_approve_and_create_nominees_creates_and_links_one_per_category(self):
        nominees = self.checkin.approve_and_create_nominees()

        self.checkin.refresh_from_db()

        self.assertEqual(
            self.checkin.status,
            SelfNominationCheckIn.STATUS_APPROVED,
        )
        self.assertEqual(len(nominees), 2)
        self.assertEqual(self.checkin.created_nominees.count(), 2)
        self.assertEqual(Nominee.objects.count(), 2)

        for nominee in nominees:
            self.assertEqual(nominee.campaign, self.campaign)
            self.assertEqual(nominee.name, self.checkin.name)
            self.assertEqual(nominee.contact_email, self.checkin.email)
            self.assertEqual(nominee.social_link, self.checkin.social_link)
            self.assertEqual(
                nominee.approval_status,
                Nominee.APPROVAL_PENDING,
            )
            self.assertTrue(nominee.is_active)

    def test_approve_and_create_nominees_does_not_overwrite_existing_nominee_photo(self):
        category = self.categories[0]
        existing = Nominee.objects.create(
            name=self.checkin.name,
            category=category,
            campaign=self.campaign,
            contact_email=self.checkin.email,
            social_link=self.checkin.social_link,
            approval_status=Nominee.APPROVAL_PENDING,
            is_active=True,
        )
        existing.photo.save(
            "existing-photo.png",
            ContentFile(b"existing-photo-data"),
            save=True,
        )
        original_photo_name = existing.photo.name
        self.checkin.categories.set([category])
        self.checkin.photo.save(
            "new-checkin-photo.png",
            ContentFile(b"new-checkin-photo-data"),
            save=True,
        )

        nominees = self.checkin.approve_and_create_nominees()

        existing.refresh_from_db()
        self.assertEqual(len(nominees), 1)
        self.assertEqual(nominees[0].pk, existing.pk)
        self.assertEqual(existing.photo.name, original_photo_name)

    def test_approve_and_create_nominees_preserves_existing_approved_nominee(self):
        category = self.categories[0]
        existing = Nominee.objects.create(
            name=self.checkin.name,
            category=category,
            campaign=self.campaign,
            contact_email=self.checkin.email,
            social_link=self.checkin.social_link,
            approval_status=Nominee.APPROVAL_APPROVED,
            is_active=True,
        )
        self.checkin.categories.set([category])

        nominees = self.checkin.approve_and_create_nominees()

        existing.refresh_from_db()
        self.assertEqual(len(nominees), 1)
        self.assertEqual(nominees[0].pk, existing.pk)
        self.assertEqual(existing.approval_status, Nominee.APPROVAL_APPROVED)
        self.assertTrue(existing.is_active)
        self.assertTrue(self.checkin.created_nominees.filter(pk=existing.pk).exists())

    def test_approve_and_create_nominees_rejects_checkin_without_categories(self):
        self.checkin.categories.clear()

        with self.assertRaisesMessage(Exception, "Check-In must have at least one category before approval."):
            self.checkin.approve_and_create_nominees()

        self.checkin.refresh_from_db()
        self.assertEqual(self.checkin.status, SelfNominationCheckIn.STATUS_PENDING)
        self.assertEqual(self.checkin.created_nominees.count(), 0)

    def test_approve_and_create_nominees_copies_checkin_photo_to_new_nominees(self):
        image_buffer = BytesIO()
        Image.new("RGB", (10, 10)).save(image_buffer, format="PNG")
        self.checkin.photo = SimpleUploadedFile(
            "approval-checkin.png",
            image_buffer.getvalue(),
            content_type="image/png",
        )
        self.checkin.save(update_fields=["photo"])

        nominees = self.checkin.approve_and_create_nominees()

        self.assertEqual(len(nominees), 2)
        for nominee in nominees:
            nominee.refresh_from_db()
            self.assertTrue(nominee.photo)
            self.assertTrue(nominee.photo.name.startswith("nominees/"))

    def test_approve_and_create_nominees_is_idempotent(self):
        first = self.checkin.approve_and_create_nominees()
        second = self.checkin.approve_and_create_nominees()

        self.assertEqual(Nominee.objects.count(), 2)
        self.assertEqual(self.checkin.created_nominees.count(), 2)
        self.assertEqual(
            {nominee.pk for nominee in first},
            {nominee.pk for nominee in second},
        )

class SelfNominationCheckInAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.model_admin = SelfNominationCheckInAdmin(SelfNominationCheckIn, admin.site)
        self.campaign = VotingCampaign.objects.create(name="Admin Check-In Campaign", is_active_campaign=True)
        self.category = Category.objects.create(name="Admin Check-In Category", is_active=True)
        self.checkin = SelfNominationCheckIn.objects.create(name="Admin Check-In Test", email="admin-checkin@example.com", social_link="https://instagram.com/admincheckin")
        self.checkin.categories.add(self.category)

    def request_with_messages(self):
        request = self.factory.post("/admin/ballot/selfnominationcheckin/")
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_admin_approval_action_prepares_nominee_and_approves_checkin(self):
        request = self.request_with_messages()
        queryset = SelfNominationCheckIn.objects.filter(pk=self.checkin.pk)

        self.model_admin.approve_and_prepare_nominees(request, queryset)

        self.checkin.refresh_from_db()
        self.assertEqual(self.checkin.status, SelfNominationCheckIn.STATUS_APPROVED)
        self.assertEqual(self.checkin.created_nominees.count(), 1)
        nominee = self.checkin.created_nominees.get()
        self.assertEqual(nominee.category, self.category)
        self.assertEqual(nominee.campaign, self.campaign)
        self.assertEqual(nominee.approval_status, Nominee.APPROVAL_PENDING)

