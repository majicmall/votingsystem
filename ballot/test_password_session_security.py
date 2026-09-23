import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PasswordAndSessionSecurityTests(TestCase):
    def setUp(self):
        self.username = "leo006c_reset"
        self.email = "leo006c-reset@example.com"
        self.old_password = "Leo-006C-Old!Pass9"
        self.new_password = "Leo-006C-New!Pass9"

        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.old_password,
        )

    def test_password_reset_for_known_email_sends_one_email(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.email},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.email])

    def test_unknown_email_does_not_reveal_account_status(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": "does-not-exist@example.com"},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

        done = self.client.get(reverse("password_reset_done"))
        self.assertContains(
            done,
            "If an account exists for that email address",
        )

    def test_invalid_reset_token_is_rejected(self):
        response = self.client.get(
            reverse(
                "password_reset_confirm",
                kwargs={
                    "uidb64": "invalid-user",
                    "token": "invalid-token",
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["validlink"])

    def test_password_reset_replaces_password(self):
        self.client.post(
            reverse("password_reset"),
            {"email": self.email},
        )

        self.assertEqual(len(mail.outbox), 1)

        body = mail.outbox[0].body
        match = re.search(
            r"https?://[^\s]+/accounts/reset/([^/]+)/([^/\s]+)/",
            body,
        )
        self.assertIsNotNone(match)

        uidb64, token = match.groups()

        response = self.client.get(
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": uidb64, "token": token},
            )
        )

        self.assertEqual(response.status_code, 302)

        reset_path = response.url

        response = self.client.post(
            reset_path,
            {
                "new_password1": self.new_password,
                "new_password2": self.new_password,
            },
        )

        self.assertRedirects(
            response,
            reverse("password_reset_complete"),
        )

        self.user.refresh_from_db()

        self.assertFalse(
            self.user.check_password(self.old_password)
        )
        self.assertTrue(
            self.user.check_password(self.new_password)
        )

    def test_old_password_fails_after_reset_and_new_password_works(self):
        self.client.post(
            reverse("password_reset"),
            {"email": self.email},
        )

        body = mail.outbox[0].body
        match = re.search(
            r"https?://[^\s]+/accounts/reset/([^/]+)/([^/\s]+)/",
            body,
        )
        self.assertIsNotNone(match)

        uidb64, token = match.groups()

        response = self.client.get(
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": uidb64, "token": token},
            )
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            response.url,
            {
                "new_password1": self.new_password,
                "new_password2": self.new_password,
            },
        )
        self.assertRedirects(
            response,
            reverse("password_reset_complete"),
        )

        self.client.logout()

        old_login = self.client.post(
            reverse("login"),
            {
                "username": self.username,
                "password": self.old_password,
            },
            REMOTE_ADDR="127.0.0.10",
        )

        self.assertEqual(old_login.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        new_login = self.client.post(
            reverse("login"),
            {
                "username": self.username,
                "password": self.new_password,
            },
            REMOTE_ADDR="127.0.0.11",
        )

        self.assertEqual(new_login.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_get_is_rejected_and_session_remains_authenticated(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("logout_then_home"))

        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_post_ends_authenticated_session(self):
        self.client.force_login(self.user)
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("logout_then_home"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_protected_dashboard_denied_after_logout(self):
        self.client.force_login(self.user)

        self.client.post(reverse("logout_then_home"))

        response = self.client.get(reverse("assoc_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('login')}?next="
            )
        )
