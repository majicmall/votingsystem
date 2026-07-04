from django.core.management.base import BaseCommand

from ballot.email_utils import absolute_url, send_nominee_approved_email


class Command(BaseCommand):
    help = "Send a polished nominee approval email test."

    def add_arguments(self, parser):
        parser.add_argument("to_email", type=str)
        parser.add_argument("--name", default="King Leo Bryant")
        parser.add_argument("--username", default=None)
        parser.add_argument("--password", default="TempPass123!")
        parser.add_argument("--nominee-path", default="/nominee/demo/")
        parser.add_argument(
            "--categories",
            default="ATL’s Hottest Artist, ATL’s Hottest Media Platform, ATL’s Hottest Event Producer",
            help="Comma-separated category names.",
        )

    def handle(self, *args, **options):
        to_email = options["to_email"]
        username = options["username"] or to_email
        categories = [
            item.strip()
            for item in options["categories"].split(",")
            if item.strip()
        ]

        send_nominee_approved_email(
            to_email=to_email,
            nominee_name=options["name"],
            username=username,
            temporary_password=options["password"],
            categories=categories,
            login_url=absolute_url("/accounts/login/"),
            dashboard_url=absolute_url("/association/dashboard/"),
            nominee_url=absolute_url(options["nominee_path"]),
        )

        self.stdout.write(self.style.SUCCESS(f"Polished nominee approval email sent to {to_email}"))
