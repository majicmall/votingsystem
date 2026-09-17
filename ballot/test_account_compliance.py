from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AccountComplianceTests(TestCase):
    def setUp(self):
        self.password = "Secure-Test-Password-927!"
        self.user = User.objects.create_user(
            username="appstore-test-user",
            password=self.password,
        )

    def test_public_compliance_pages_are_public(self):
        for route_name in (
            "account_deletion_info",
            "privacy_policy",
            "terms_of_service",
        ):
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 200)

    def test_account_settings_requires_login(self):
        response = self.client.get(reverse("account_settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_delete_account_requires_login(self):
        response = self.client.get(reverse("delete_account"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_get_delete_page_never_deletes_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("delete_account"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_wrong_password_does_not_delete_user(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("delete_account"),
            {
                "password": "wrong-password",
                "confirmation": "DELETE",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_confirmation_must_match_exactly(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("delete_account"),
            {
                "password": self.password,
                "confirmation": "delete",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_valid_confirmation_deletes_account(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("delete_account"),
            {
                "password": self.password,
                "confirmation": "DELETE",
            },
        )

        self.assertRedirects(
            response,
            reverse("account_deleted"),
        )
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_deleted_user_is_logged_out(self):
        self.client.force_login(self.user)

        self.client.post(
            reverse("delete_account"),
            {
                "password": self.password,
                "confirmation": "DELETE",
            },
        )

        response = self.client.get(reverse("account_settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


class AccountDeletionCascadeTests(TestCase):
    def setUp(self):
        self.password = "Cascade-Test-Password-927!"
        self.user = User.objects.create_user(
            username="cascade-test-user",
            email="cascade@example.com",
            password=self.password,
        )

    def test_deletion_removes_atl_megaverse_connection(self):
        from megaverse.models import MegaverseConnection

        connection = MegaverseConnection.objects.create(
            user=self.user,
            megaverse_user_ref="00000000-0000-0000-0000-000000000927",
            is_linked=True,
        )
        connection_pk = connection.pk

        self.client.force_login(self.user)

        response = self.client.post(
            reverse("delete_account"),
            {
                "password": self.password,
                "confirmation": "DELETE",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(
            MegaverseConnection.objects.filter(pk=connection_pk).exists()
        )
