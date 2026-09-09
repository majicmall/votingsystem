import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase, override_settings

from .services import (
    MegaverseAPIError,
    MegaverseClient,
    MegaverseConfigurationError,
    MegaverseConnectionError,
)


@override_settings(
    MEGAVERSE_API_BASE_URL="https://megaverse.example.test",
    MEGAVERSE_API_KEY="test-secret-key",
    MEGAVERSE_API_TIMEOUT=5,
)
class MegaverseClientTests(SimpleTestCase):
    def test_missing_base_url_fails_closed(self):
        with override_settings(MEGAVERSE_API_BASE_URL=""):
            client = MegaverseClient()

            with self.assertRaisesRegex(
                MegaverseConfigurationError,
                "MEGAVERSE_API_BASE_URL is not configured",
            ):
                client.get("/health/")

    def test_missing_api_key_fails_closed(self):
        with override_settings(MEGAVERSE_API_KEY=""):
            client = MegaverseClient()

            with self.assertRaisesRegex(
                MegaverseConfigurationError,
                "MEGAVERSE_API_KEY is not configured",
            ):
                client.get("/health/")

    @patch("megaverse.services.urlopen")
    def test_get_builds_authenticated_request_and_query(self, mock_urlopen):
        response = MagicMock()
        response.getcode.return_value = 200
        response.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response

        result = MegaverseClient().get(
            "/api/storefronts/",
            query={"zone": "atl", "unused": None},
        )

        request = mock_urlopen.call_args.args[0]

        self.assertEqual(
            request.full_url,
            "https://megaverse.example.test/api/storefronts/?zone=atl",
        )
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-secret-key",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, {"ok": True})

    @patch("megaverse.services.urlopen")
    def test_post_sends_json_payload(self, mock_urlopen):
        response = MagicMock()
        response.getcode.return_value = 201
        response.read.return_value = json.dumps({"id": "abc123"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response

        result = MegaverseClient().post(
            "/api/connections/",
            payload={"atl_user_ref": "42"},
        )

        request = mock_urlopen.call_args.args[0]

        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"atl_user_ref": "42"},
        )
        self.assertEqual(
            request.get_header("Content-type"),
            "application/json",
        )
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data, {"id": "abc123"})

    @patch("megaverse.services.urlopen")
    def test_http_error_becomes_api_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://megaverse.example.test/api/storefronts/",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"Storefront not found."}'),
        )

        with self.assertRaises(MegaverseAPIError) as context:
            MegaverseClient().get("/api/storefronts/")

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(str(context.exception), "Storefront not found.")

    @patch("megaverse.services.urlopen")
    def test_network_error_becomes_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("offline")

        with self.assertRaises(MegaverseConnectionError):
            MegaverseClient().get("/health/")

    @patch("megaverse.services.urlopen")
    def test_invalid_json_becomes_api_error(self, mock_urlopen):
        response = MagicMock()
        response.getcode.return_value = 200
        response.read.return_value = b"not-json"
        mock_urlopen.return_value.__enter__.return_value = response

        with self.assertRaisesRegex(
            MegaverseAPIError,
            "returned invalid JSON",
        ):
            MegaverseClient().get("/health/")
