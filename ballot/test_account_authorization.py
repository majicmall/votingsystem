
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ballot.models import (
    AssociationMembership,
    Category,
    NominationCategoryRequest,
    Nominee,
)


User = get_user_model()


class NomineeAuthorizationTests(TestCase):
    def setUp(self):
        self.password = "Leo-QA-006B-Strong!Pass9"

        self.user_a = User.objects.create_user(
            username="leo006b_user_a",
            email="leo006b-a@example.com",
            password=self.password,
        )
        self.user_b = User.objects.create_user(
            username="leo006b_user_b",
            email="leo006b-b@example.com",
            password=self.password,
        )
        self.staff = User.objects.create_user(
            username="leo006b_staff",
            email="leo006b-staff@example.com",
            password=self.password,
            is_staff=True,
        )

        self.category_a = Category.objects.create(
            name="006B Security Category A",
            slug="006b-security-category-a",
            is_active=True,
        )
        self.category_b = Category.objects.create(
            name="006B Security Category B",
            slug="006b-security-category-b",
            is_active=True,
        )

        self.nominee_a = Nominee.objects.create(
            id="006b-nominee-a",
            name="006B Nominee A",
            category=self.category_a,
            contact_email="leo006b-a@example.com",
            approval_status=Nominee.APPROVAL_APPROVED,
            is_active=True,
        )
        self.nominee_b = Nominee.objects.create(
            id="006b-nominee-b",
            name="006B Nominee B",
            category=self.category_a,
            contact_email="leo006b-b@example.com",
            approval_status=Nominee.APPROVAL_APPROVED,
            is_active=True,
        )

        AssociationMembership.objects.create(
            user=self.user_a,
            nominee=self.nominee_a,
            is_active=True,
        )
        AssociationMembership.objects.create(
            user=self.user_b,
            nominee=self.nominee_b,
            is_active=True,
        )

    def test_anonymous_user_is_redirected_from_management_routes(self):
        routes = [
            reverse("assoc_nominee_edit", args=[self.nominee_a.id]),
            reverse("assoc_nominee_regen_link", args=[self.nominee_a.id]),
            reverse("request_categories", args=[self.nominee_a.id]),
            reverse("assoc_nominee_delete", args=[self.nominee_a.id]),
        ]

        for url in routes:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/login/", response.url)

    def test_owner_can_open_edit_page(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("assoc_nominee_edit", args=[self.nominee_a.id])
        )

        self.assertEqual(response.status_code, 200)

    def test_user_cannot_open_another_users_edit_page(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("assoc_nominee_edit", args=[self.nominee_b.id])
        )

        self.assertEqual(response.status_code, 302)
        self.nominee_b.refresh_from_db()
        self.assertEqual(self.nominee_b.name, "006B Nominee B")

    def test_user_cannot_regenerate_another_users_upload_token(self):
        self.client.force_login(self.user_a)

        original_token = self.nominee_b.upload_token

        response = self.client.post(
            reverse("assoc_nominee_regen_link", args=[self.nominee_b.id])
        )

        self.assertEqual(response.status_code, 302)

        self.nominee_b.refresh_from_db()
        self.assertEqual(self.nominee_b.upload_token, original_token)

    def test_owner_can_regenerate_own_upload_token(self):
        self.client.force_login(self.user_a)

        original_token = self.nominee_a.upload_token

        response = self.client.post(
            reverse("assoc_nominee_regen_link", args=[self.nominee_a.id])
        )

        self.assertEqual(response.status_code, 302)

        self.nominee_a.refresh_from_db()
        self.assertNotEqual(self.nominee_a.upload_token, original_token)

    def test_user_cannot_archive_another_users_nominee(self):
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse("assoc_nominee_delete", args=[self.nominee_b.id])
        )

        self.assertEqual(response.status_code, 302)

        self.nominee_b.refresh_from_db()
        self.assertTrue(self.nominee_b.is_active)
        self.assertIsNone(self.nominee_b.deleted_at)

    def test_owner_can_archive_own_nominee(self):
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse("assoc_nominee_delete", args=[self.nominee_a.id])
        )

        self.assertEqual(response.status_code, 302)

        self.nominee_a.refresh_from_db()
        self.assertFalse(self.nominee_a.is_active)
        self.assertIsNotNone(self.nominee_a.deleted_at)

    def test_user_cannot_create_category_request_for_another_users_nominee(self):
        self.client.force_login(self.user_a)

        before = NominationCategoryRequest.objects.count()

        response = self.client.post(
            reverse("request_categories", args=[self.nominee_b.id]),
            {"categories": [self.category_b.id]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(NominationCategoryRequest.objects.count(), before)

        self.assertFalse(
            NominationCategoryRequest.objects.filter(
                requester=self.user_a,
                source_nominee=self.nominee_b,
                target_category=self.category_b,
            ).exists()
        )

    def test_staff_can_open_both_nominee_edit_pages(self):
        self.client.force_login(self.staff)

        for nominee in (self.nominee_a, self.nominee_b):
            response = self.client.get(
                reverse("assoc_nominee_edit", args=[nominee.id])
            )
            self.assertEqual(response.status_code, 200)

    def test_inactive_membership_does_not_grant_management_access(self):
        membership = AssociationMembership.objects.get(
            user=self.user_a,
            nominee=self.nominee_a,
        )
        membership.is_active = False
        membership.save(update_fields=["is_active"])

        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("assoc_nominee_edit", args=[self.nominee_a.id])
        )

        self.assertEqual(response.status_code, 302)
