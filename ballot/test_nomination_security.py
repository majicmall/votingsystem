from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.test import RequestFactory
from ballot.nomination_security import HONEYPOT_FIELD, nomination_honeypot_triggered


class NominationSecurityTests(SimpleTestCase):
    def test_normal_submission_does_not_trigger_honeypot(self):
        request = RequestFactory().post("/nominee/signup/", {})
        self.assertFalse(nomination_honeypot_triggered(request))

    def test_filled_honeypot_is_detected(self):
        request = RequestFactory().post("/nominee/signup/", {HONEYPOT_FIELD: "spam"})
        self.assertTrue(nomination_honeypot_triggered(request))

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_honeypot_rejected_by_nomination_endpoint(self):
        response = self.client.post(reverse("nominee_signup"), {HONEYPOT_FIELD: "BOT_TEST"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Invalid nomination submission.", status_code=400)
