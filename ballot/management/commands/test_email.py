from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send a test ATL's Hottest Awards email."

    def add_arguments(self, parser):
        parser.add_argument("to_email", type=str)

    def handle(self, *args, **options):
        to_email = options["to_email"]

        subject = "ATL's Hottest Awards email test"

        text_body = """ATL's Hottest Awards

This is a production email test.

If you received this, outgoing email is working.
"""

        html_body = """
        <div style="margin:0;padding:24px;background:#050505;color:#ffffff;font-family:Georgia,serif;">
          <div style="max-width:680px;margin:0 auto;border:1px solid #ffd76a;border-radius:22px;overflow:hidden;background:linear-gradient(135deg,#000000,#3a0610);">
            <div style="padding:26px;background:linear-gradient(135deg,#000000,#7d0616 55%,#000000);border-bottom:1px solid rgba(255,215,106,0.55);">
              <p style="margin:0 0 8px;color:#ffd76a;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Email Test</p>
              <h1 style="margin:0;color:#ffffff;font-size:34px;">ATL's Hottest Awards</h1>
            </div>
            <div style="padding:26px;">
              <p style="font-size:18px;line-height:1.6;color:#ffffff;">This is a production email test.</p>
              <p style="color:#ffd76a;">If you received this, outgoing email is working.</p>
            </div>
          </div>
        </div>
        """

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)

        self.stdout.write(self.style.SUCCESS(f"Test email sent to {to_email}"))
        self.stdout.write(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
