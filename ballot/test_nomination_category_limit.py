from django.test import TestCase
from ballot.forms import NomineeSignupForm
from ballot.models import Category


class NominationCategoryLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categories = [
            Category.objects.create(name=f"Security Test Category {i}", is_active=True)
            for i in range(1, 7)
        ]

    def make_form(self, count):
        return NomineeSignupForm(data={
            "nominator_name": "Security Test Fan",
            "nominator_email": "security-test@example.com",
            "nominee_name": "Security Test Nominee",
            "categories": [str(c.pk) for c in self.categories[:count]],
            "website": "https://example.com",
        })

    def test_five_categories_allowed(self):
        form = self.make_form(5)
        self.assertTrue(form.is_valid(), form.errors)

    def test_six_categories_rejected(self):
        form = self.make_form(6)
        self.assertFalse(form.is_valid())
        self.assertIn("categories", form.errors)
        self.assertIn("Choose up to 5 categories.", str(form.errors["categories"]))

    def test_one_category_allowed(self):
        form = self.make_form(1)
        self.assertTrue(form.is_valid(), form.errors)
