from unittest.mock import Mock, patch
from django.test import SimpleTestCase, RequestFactory, override_settings
from ballot.nomination_security import verify_nomination_turnstile


class NominationTurnstileTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(NOMINATION_TURNSTILE_ENABLED=False)
    def test_disabled_turnstile_preserves_existing_flow(self):
        self.assertTrue(verify_nomination_turnstile(self.factory.post("/", {})))

    @override_settings(NOMINATION_TURNSTILE_ENABLED=True, NOMINATION_TURNSTILE_SITE_KEY="test-site", NOMINATION_TURNSTILE_SECRET_KEY="test-secret")
    def test_missing_token_rejected(self):
        self.assertFalse(verify_nomination_turnstile(self.factory.post("/", {})))

    @override_settings(NOMINATION_TURNSTILE_ENABLED=True, NOMINATION_TURNSTILE_SITE_KEY="test-site", NOMINATION_TURNSTILE_SECRET_KEY="test-secret")
    @patch("requests.post")
    def test_valid_token_accepted(self, post):
        post.return_value.json.return_value = {"success": True}
        request = self.factory.post("/", {"cf-turnstile-response": "valid-test-token"})
        self.assertTrue(verify_nomination_turnstile(request))
        post.assert_called_once()

    @override_settings(NOMINATION_TURNSTILE_ENABLED=True, NOMINATION_TURNSTILE_SITE_KEY="test-site", NOMINATION_TURNSTILE_SECRET_KEY="test-secret")
    @patch("requests.post")
    def test_invalid_token_rejected(self, post):
        post.return_value.json.return_value = {"success": False}
        request = self.factory.post("/", {"cf-turnstile-response": "invalid-test-token"})
        self.assertFalse(verify_nomination_turnstile(request))
