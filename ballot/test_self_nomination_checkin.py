import shutil
import tempfile
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ballot.forms import SelfNominationCheckInForm
from ballot.models import Category, SelfNominationCheckIn


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
