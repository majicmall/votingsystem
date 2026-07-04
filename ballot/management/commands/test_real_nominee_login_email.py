from django.core.management.base import BaseCommand

from ballot.models import Category, Nominee


class Command(BaseCommand):
    help = "Create or update a real nominee account, set a temporary password, and send the polished approval email."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)
        parser.add_argument("--name", default="King Leo Bryant")
        parser.add_argument("--category", default="ATL’s Hottest Artist")
        parser.add_argument("--password", default="TempPass123!")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        name = options["name"].strip()
        category_name = options["category"].strip()
        password = options["password"]

        category, _ = Category.objects.get_or_create(
            name=category_name,
            defaults={
                "slug": "test-atls-hottest-artist",
                "is_active": True,
                "sort_order": 999,
            },
        )

        nominee, _ = Nominee.objects.get_or_create(
            name=name,
            category=category,
            defaults={
                "contact_email": email,
                "approval_status": Nominee.APPROVAL_APPROVED,
                "is_active": True,
            },
        )

        nominee.contact_email = email
        nominee.approval_status = Nominee.APPROVAL_APPROVED
        nominee.is_active = True
        nominee.save()

        user = nominee.send_approval_notice(temporary_password=password)

        self.stdout.write(self.style.SUCCESS("Real nominee approval/login email sent."))
        self.stdout.write(f"Nominee: {nominee.name}")
        self.stdout.write(f"Category: {nominee.category.name}")
        self.stdout.write(f"Username: {user.username}")
        self.stdout.write(f"Email: {user.email}")
        self.stdout.write(f"Temporary password set to: {password}")
