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

class CommunicationPreferenceTests(TestCase):
    def setUp(self):
        self.password = "Preference-Test-Password-927!"
        self.user = User.objects.create_user(
            username="preference-test-user",
            email="Preference@Test.Example.com",
            password=self.password,
        )
        self.client.force_login(self.user)

    def test_account_settings_creates_email_preference(self):
        from ballot.models import CommunicationPreference

        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)

        preference = CommunicationPreference.objects.get(
            email="preference@test.example.com"
        )
        self.assertEqual(preference.user, self.user)
        self.assertFalse(preference.marketing_allowed)

    def test_enable_promotional_communications_records_consent(self):
        from ballot.models import CommunicationPreference

        self.client.get(reverse("account_settings"))

        response = self.client.post(
            reverse("account_settings"),
            {"communications_action": "enable"},
        )

        self.assertEqual(response.status_code, 302)

        preference = CommunicationPreference.objects.get(
            email="preference@test.example.com"
        )
        self.assertTrue(preference.marketing_allowed)
        self.assertIsNotNone(preference.consented_at)
        self.assertEqual(preference.consent_version, "2026-09-v1")
        self.assertIsNone(preference.withdrawn_at)

    def test_withdrawal_preserves_consent_evidence(self):
        from ballot.models import CommunicationPreference

        self.client.get(reverse("account_settings"))

        self.client.post(
            reverse("account_settings"),
            {"communications_action": "enable"},
        )

        preference = CommunicationPreference.objects.get(
            email="preference@test.example.com"
        )
        consented_at = preference.consented_at
        consent_version = preference.consent_version

        response = self.client.post(
            reverse("account_settings"),
            {"communications_action": "disable"},
        )

        self.assertEqual(response.status_code, 302)

        preference.refresh_from_db()

        self.assertFalse(preference.marketing_allowed)
        self.assertIsNotNone(preference.withdrawn_at)
        self.assertEqual(preference.consented_at, consented_at)
        self.assertEqual(preference.consent_version, consent_version)

    def test_invalid_action_does_not_enable_marketing(self):
        from ballot.models import CommunicationPreference

        self.client.get(reverse("account_settings"))

        self.client.post(
            reverse("account_settings"),
            {"communications_action": "invalid"},
        )

        preference = CommunicationPreference.objects.get(
            email="preference@test.example.com"
        )
        self.assertFalse(preference.marketing_allowed)

    def test_account_deletion_preserves_email_preference_but_unlinks_user(self):
        from ballot.models import CommunicationPreference

        self.client.get(reverse("account_settings"))

        preference = CommunicationPreference.objects.get(
            email="preference@test.example.com"
        )

        self.client.post(
            reverse("delete_account"),
            {
                "password": self.password,
                "confirmation": "DELETE",
            },
        )

        preference.refresh_from_db()

        self.assertFalse(
            User.objects.filter(username="preference-test-user").exists()
        )
        self.assertIsNone(preference.user)


class PublicUnsubscribeTests(TestCase):
    def setUp(self):
        from ballot.email_utils import communications_unsubscribe_token
        from ballot.models import CommunicationPreference

        self.email = "unsubscribe-test@example.com"

        self.preference = CommunicationPreference.objects.create(
            email=self.email,
            marketing_allowed=True,
        )
        self.preference.grant_marketing_consent()

        self.token = communications_unsubscribe_token(self.email)
        self.url = reverse(
            "communications_unsubscribe",
            kwargs={"token": self.token},
        )

    def test_unsubscribe_page_is_public(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_get_does_not_unsubscribe(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.preference.refresh_from_db()

        self.assertTrue(self.preference.marketing_allowed)
        self.assertIsNone(self.preference.withdrawn_at)

    def test_post_unsubscribes(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)

        self.preference.refresh_from_db()

        self.assertFalse(self.preference.marketing_allowed)
        self.assertIsNotNone(self.preference.withdrawn_at)

    def test_unsubscribe_preserves_consent_evidence(self):
        consented_at = self.preference.consented_at
        consent_version = self.preference.consent_version

        self.client.post(self.url)

        self.preference.refresh_from_db()

        self.assertEqual(self.preference.consented_at, consented_at)
        self.assertEqual(self.preference.consent_version, consent_version)

    def test_repeated_unsubscribe_is_idempotent(self):
        self.client.post(self.url)

        self.preference.refresh_from_db()
        first_withdrawn_at = self.preference.withdrawn_at

        self.client.post(self.url)

        self.preference.refresh_from_db()

        self.assertFalse(self.preference.marketing_allowed)
        self.assertEqual(
            self.preference.withdrawn_at,
            first_withdrawn_at,
        )

    def test_tampered_token_fails_closed(self):
        tampered_url = reverse(
            "communications_unsubscribe",
            kwargs={"token": self.token + "tampered"},
        )

        response = self.client.get(tampered_url)

        self.assertEqual(response.status_code, 400)

        self.preference.refresh_from_db()
        self.assertTrue(self.preference.marketing_allowed)

    def test_valid_token_without_existing_preference_is_safe(self):
        from ballot.email_utils import communications_unsubscribe_token

        token = communications_unsubscribe_token(
            "unknown-person@example.com"
        )

        url = reverse(
            "communications_unsubscribe",
            kwargs={"token": token},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)


class CommunicationPreferenceOwnershipTests(TestCase):
    def test_existing_user_preference_follows_changed_email(self):
        from ballot.models import CommunicationPreference

        user = User.objects.create_user(
            username="changed-email-user",
            email="old-email@example.com",
            password="Ownership-Test-927!",
        )

        preference = CommunicationPreference.objects.create(
            user=user,
            email="old-email@example.com",
            marketing_allowed=True,
        )

        user.email = "new-email@example.com"
        user.save(update_fields=["email"])

        self.client.force_login(user)

        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)

        preference.refresh_from_db()

        self.assertEqual(preference.user, user)
        self.assertEqual(preference.email, "new-email@example.com")
        self.assertEqual(
            CommunicationPreference.objects.filter(user=user).count(),
            1,
        )

    def test_preference_owned_by_another_user_is_not_taken_over(self):
        from ballot.models import CommunicationPreference

        owner = User.objects.create_user(
            username="preference-owner",
            email="shared@example.com",
            password="Ownership-Test-927!",
        )
        other = User.objects.create_user(
            username="other-preference-user",
            email="shared@example.com",
            password="Ownership-Test-928!",
        )

        preference = CommunicationPreference.objects.create(
            user=owner,
            email="shared@example.com",
            marketing_allowed=True,
        )

        self.client.force_login(other)

        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)

        preference.refresh_from_db()

        self.assertEqual(preference.user, owner)
        self.assertFalse(
            CommunicationPreference.objects.filter(user=other).exists()
        )


class SubmissionCommunicationConsentTests(TestCase):
    def setUp(self):
        from ballot.models import Category, VotingCampaign

        self.campaign = VotingCampaign.objects.create(
            name="Consent Test Campaign",
            slug="consent-test-campaign",
            nominations_enabled=True,
            voting_enabled=False,
            is_active_campaign=True,
        )

        self.category = Category.objects.create(
            name="Consent Test Category",
            group="Entertainment",
            is_active=True,
        )

    def test_nomination_checked_consent_enables_current_preference(self):
        from ballot.models import CommunicationPreference

        email = "nomination-optin@example.com"

        response = self.client.post(
            reverse("nominee_signup"),
            {
                "nominator_name": "Consent Tester",
                "nominator_email": email,
                "communications_consent": "on",
                "nominee_name": "Consent Nominee One",
                "categories": [str(self.category.pk)],
                "website": "",
                "social_link": "",
                "contact_email": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        preference = CommunicationPreference.objects.get(email=email)

        self.assertTrue(preference.marketing_allowed)
        self.assertIsNotNone(preference.consented_at)
        self.assertEqual(
            preference.consent_version,
            "2026-09-v1",
        )
        self.assertIsNone(preference.withdrawn_at)

    def test_nomination_unchecked_does_not_revoke_existing_preference(self):
        from ballot.models import CommunicationPreference

        email = "nomination-existing@example.com"

        preference = CommunicationPreference.objects.create(
            email=email,
            marketing_allowed=False,
        )
        preference.grant_marketing_consent()

        original_consented_at = preference.consented_at

        response = self.client.post(
            reverse("nominee_signup"),
            {
                "nominator_name": "Existing Consent Tester",
                "nominator_email": email,
                "nominee_name": "Consent Nominee Two",
                "categories": [str(self.category.pk)],
                "website": "",
                "social_link": "",
                "contact_email": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        preference.refresh_from_db()

        self.assertTrue(preference.marketing_allowed)
        self.assertEqual(
            preference.consented_at,
            original_consented_at,
        )
        self.assertIsNone(preference.withdrawn_at)

    def test_checkin_checked_consent_enables_current_preference(self):
        from ballot.models import CommunicationPreference

        email = "checkin-optin@example.com"

        response = self.client.post(
            reverse("self_nomination_checkin"),
            {
                "name": "Check-In Consent Tester",
                "email": email,
                "website": "https://example.com",
                "social_link": "",
                "communications_consent": "on",
                "categories": [str(self.category.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)

        preference = CommunicationPreference.objects.get(email=email)

        self.assertTrue(preference.marketing_allowed)
        self.assertIsNotNone(preference.consented_at)
        self.assertEqual(
            preference.consent_version,
            "2026-09-v1",
        )
        self.assertIsNone(preference.withdrawn_at)

    def test_checkin_unchecked_does_not_revoke_existing_preference(self):
        from ballot.models import CommunicationPreference

        email = "checkin-existing@example.com"

        preference = CommunicationPreference.objects.create(
            email=email,
            marketing_allowed=False,
        )
        preference.grant_marketing_consent()

        original_consented_at = preference.consented_at

        response = self.client.post(
            reverse("self_nomination_checkin"),
            {
                "name": "Existing Check-In Tester",
                "email": email,
                "website": "https://example.com",
                "social_link": "",
                "categories": [str(self.category.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)

        preference.refresh_from_db()

        self.assertTrue(preference.marketing_allowed)
        self.assertEqual(
            preference.consented_at,
            original_consented_at,
        )
        self.assertIsNone(preference.withdrawn_at)
