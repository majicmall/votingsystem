import time
import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import MegaverseConnection
from .services import MegaverseConnectionError


User = get_user_model()


@override_settings(
    MEGAVERSE_API_BASE_URL="https://majicmall.example.test",
    MEGAVERSE_API_KEY="bridge-secret",
    MEGAVERSE_API_TIMEOUT=5,
)
class MegaverseIdentityLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="atl-user",
            email="atl@example.com",
            password="test-password-123",
        )
        self.client.force_login(self.user)

    def begin_link(self):
        response = self.client.get(reverse("megaverse:link_start"))

        self.assertEqual(response.status_code, 302)

        parsed = urlparse(response["Location"])
        query = parse_qs(parsed.query)

        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            "https://majicmall.example.test/connect/atls-hottest/",
        )

        state = query["state"][0]

        return state

    def callback_url(self, *, state, code="code-123", error=None):
        params = {"state": state}

        if code:
            params["code"] = code

        if error:
            params["error"] = error
            params.pop("code", None)

        query = "&".join(f"{key}={value}" for key, value in params.items())

        return f"{reverse('megaverse:link_callback')}?{query}"

    def test_start_link_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("megaverse:link_start"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_start_link_generates_state_and_redirects_to_fixed_authorization_path(self):
        state = self.begin_link()

        session_state = self.client.session["megaverse_link_state"]

        self.assertEqual(session_state["value"], state)
        self.assertIn("issued_at", session_state)

    @override_settings(MEGAVERSE_API_BASE_URL="")
    def test_start_link_fails_closed_without_configuration(self):
        response = self.client.get(reverse("megaverse:link_start"))

        self.assertRedirects(
            response,
            reverse("megaverse:link_result"),
            fetch_redirect_response=False,
        )

        result = self.client.session["megaverse_link_result"]

        self.assertFalse(result["success"])

    @patch("megaverse.views.MegaverseClient.post")
    def test_state_mismatch_rejected_before_exchange(self, mock_post):
        self.begin_link()

        response = self.client.get(
            self.callback_url(
                state="wrong-state",
                code="code-123",
            )
        )

        self.assertRedirects(
            response,
            reverse("megaverse:link_result"),
            fetch_redirect_response=False,
        )

        mock_post.assert_not_called()

    @patch("megaverse.views.MegaverseClient.post")
    def test_expired_state_rejected_before_exchange(self, mock_post):
        state = self.begin_link()

        session = self.client.session
        session["megaverse_link_state"] = {
            "value": state,
            "issued_at": int(time.time()) - 1000,
        }
        session.save()

        self.client.get(
            self.callback_url(
                state=state,
                code="code-123",
            )
        )

        mock_post.assert_not_called()

    @patch("megaverse.views.MegaverseClient.post")
    def test_denial_does_not_exchange_code(self, mock_post):
        state = self.begin_link()

        response = self.client.get(
            self.callback_url(
                state=state,
                code=None,
                error="access_denied",
            )
        )

        self.assertRedirects(
            response,
            reverse("megaverse:link_result"),
            fetch_redirect_response=False,
        )

        mock_post.assert_not_called()

    @patch("megaverse.views.MegaverseClient.post")
    def test_successful_exchange_links_account(self, mock_post):
        megaverse_ref = str(uuid.uuid4())

        mock_post.return_value = MagicMock(
            status_code=200,
            data={
                "ok": True,
                "megaverse_user_ref": megaverse_ref,
            },
        )

        state = self.begin_link()

        response = self.client.get(
            self.callback_url(
                state=state,
                code="valid-code",
            )
        )

        self.assertRedirects(
            response,
            reverse("megaverse:link_result"),
            fetch_redirect_response=False,
        )

        connection = MegaverseConnection.objects.get(user=self.user)

        self.assertTrue(connection.is_linked)
        self.assertEqual(connection.megaverse_user_ref, megaverse_ref)
        self.assertIsNotNone(connection.linked_at)
        self.assertIsNotNone(connection.last_synced_at)

        mock_post.assert_called_once_with(
            "/api/megaverse/identity/exchange/",
            payload={"code": "valid-code"},
        )

    @patch("megaverse.views.MegaverseClient.post")
    def test_invalid_uuid_is_rejected(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            data={
                "ok": True,
                "megaverse_user_ref": "not-a-valid-uuid",
            },
        )

        state = self.begin_link()

        self.client.get(
            self.callback_url(
                state=state,
                code="valid-code",
            )
        )

        self.assertFalse(
            MegaverseConnection.objects.filter(
                user=self.user,
                is_linked=True,
            ).exists()
        )

    @patch("megaverse.views.MegaverseClient.post")
    def test_existing_different_identity_is_not_overwritten(self, mock_post):
        original_ref = str(uuid.uuid4())
        replacement_ref = str(uuid.uuid4())

        MegaverseConnection.objects.create(
            user=self.user,
            megaverse_user_ref=original_ref,
            is_linked=True,
        )

        mock_post.return_value = MagicMock(
            status_code=200,
            data={
                "ok": True,
                "megaverse_user_ref": replacement_ref,
            },
        )

        state = self.begin_link()

        self.client.get(
            self.callback_url(
                state=state,
                code="valid-code",
            )
        )

        connection = MegaverseConnection.objects.get(user=self.user)

        self.assertEqual(connection.megaverse_user_ref, original_ref)

    @patch("megaverse.views.MegaverseClient.post")
    def test_same_megaverse_identity_cannot_link_to_two_atl_accounts(self, mock_post):
        shared_ref = str(uuid.uuid4())

        other_user = User.objects.create_user(
            username="other-user",
            email="other@example.com",
            password="test-password-456",
        )

        MegaverseConnection.objects.create(
            user=other_user,
            megaverse_user_ref=shared_ref,
            is_linked=True,
        )

        mock_post.return_value = MagicMock(
            status_code=200,
            data={
                "ok": True,
                "megaverse_user_ref": shared_ref,
            },
        )

        state = self.begin_link()

        self.client.get(
            self.callback_url(
                state=state,
                code="valid-code",
            )
        )

        self.assertFalse(
            MegaverseConnection.objects.filter(
                user=self.user,
                megaverse_user_ref=shared_ref,
            ).exists()
        )

    @patch("megaverse.views.MegaverseClient.post")
    def test_relinking_same_identity_is_idempotent(self, mock_post):
        megaverse_ref = str(uuid.uuid4())

        connection = MegaverseConnection.objects.create(
            user=self.user,
            megaverse_user_ref=megaverse_ref,
            is_linked=True,
        )

        original_linked_at = connection.linked_at
        self.assertIsNone(original_linked_at)

        mock_post.return_value = MagicMock(
            status_code=200,
            data={
                "ok": True,
                "megaverse_user_ref": megaverse_ref,
            },
        )

        state = self.begin_link()

        self.client.get(
            self.callback_url(
                state=state,
                code="valid-code",
            )
        )

        connection.refresh_from_db()

        self.assertEqual(connection.megaverse_user_ref, megaverse_ref)
        self.assertTrue(connection.is_linked)
        self.assertIsNotNone(connection.linked_at)

    @patch("megaverse.views.MegaverseClient.post")
    def test_exchange_network_failure_does_not_link_account(self, mock_post):
        mock_post.side_effect = MegaverseConnectionError(
            "Unable to connect to the MajicMall Megaverse API."
        )

        state = self.begin_link()

        self.client.get(
            self.callback_url(
                state=state,
                code="valid-code",
            )
        )

        self.assertFalse(
            MegaverseConnection.objects.filter(
                user=self.user,
                is_linked=True,
            ).exists()
        )

    def test_result_is_no_store_and_consumes_message(self):
        session = self.client.session
        session["megaverse_link_result"] = {
            "success": True,
            "title": "Connected",
            "message": "Success.",
        }
        session.save()

        response = self.client.get(reverse("megaverse:link_result"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn(
            "megaverse_link_result",
            self.client.session,
        )
