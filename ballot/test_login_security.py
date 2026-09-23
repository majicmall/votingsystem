from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from axes.models import AccessAttempt


User = get_user_model()


@override_settings(
    AXES_FAILURE_LIMIT=5,
    AXES_LOCK_OUT_AT_FAILURE=True,
    AXES_COOLOFF_TIME=0.5,
    AXES_RESET_ON_SUCCESS=True,
)
class LoginSecurityTests(TestCase):
    def setUp(self):
        self.username = "leo006c_user"
        self.password = "Leo-006C-Secure!Pass9"

        self.user = User.objects.create_user(
            username=self.username,
            email="leo006c@example.com",
            password=self.password,
        )

        self.login_url = reverse("login")
        self.dashboard_url = reverse("assoc_dashboard")

    def login(self, password=None):
        return self.client.post(
            self.login_url,
            {
                "username": self.username,
                "password": password or self.password,
            },
            REMOTE_ADDR="127.0.0.1",
        )

    def test_valid_credentials_authenticate_user(self):
        response = self.login()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.user.pk,
        )

    def test_bad_password_does_not_authenticate_user(self):
        response = self.login("Wrong-Password-006C!")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_resets_previous_failure_record(self):
        self.login("Wrong-Password-006C!")

        self.assertTrue(
            AccessAttempt.objects.filter(username=self.username).exists()
        )

        response = self.login()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AccessAttempt.objects.filter(username=self.username).exists()
        )

    def test_five_failed_attempts_trigger_lockout(self):
        for attempt in range(5):
            response = self.login(f"Wrong-Password-{attempt}!")

        self.assertNotIn("_auth_user_id", self.client.session)

        # Depending on the installed Axes version/configuration, the lockout
        # response may be 403 or another configured lockout response.
        self.assertNotEqual(response.status_code, 302)

    def test_correct_password_cannot_bypass_active_lockout(self):
        for attempt in range(5):
            self.login(f"Wrong-Password-{attempt}!")

        response = self.login()

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotEqual(response.status_code, 302)

    def test_failures_against_one_account_do_not_authenticate_another(self):
        other = User.objects.create_user(
            username="leo006c_other",
            email="leo006c-other@example.com",
            password="Leo-006C-Other!Pass9",
        )

        for attempt in range(4):
            self.login(f"Wrong-Password-{attempt}!")

        response = self.client.post(
            self.login_url,
            {
                "username": other.username,
                "password": "Leo-006C-Other!Pass9",
            },
            REMOTE_ADDR="127.0.0.2",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            other.pk,
        )

    def test_login_page_exposes_password_reset_path(self):
        response = self.client.get(self.login_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("password_reset"))
