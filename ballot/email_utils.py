from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.defaultfilters import linebreaksbr
from django.utils.html import escape


def absolute_url(path: str) -> str:
    """
    Build a production-safe absolute URL.

    Uses SITE_URL when available. Otherwise falls back to Render live domain.
    """
    base_url = getattr(settings, "SITE_URL", "") or "https://atlshottestawards.onrender.com"
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def send_nominee_approved_email(
    *,
    to_email: str,
    nominee_name: str,
    username: str,
    login_url: str | None = None,
    dashboard_url: str | None = None,
    nominee_url: str | None = None,
    temporary_password: str | None = None,
) -> None:
    """
    Send the official nominee approval email.
    """
    login_url = login_url or absolute_url("/accounts/login/")
    dashboard_url = dashboard_url or absolute_url("/association/dashboard/")

    nominee_name_safe = escape(nominee_name or "Nominee")
    username_safe = escape(username or to_email)
    to_email_safe = escape(to_email)

    password_block_text = ""
    password_block_html = ""

    if temporary_password:
        password_block_text = f"""

Temporary password:
{temporary_password}

For security, please log in and change your password when the password reset feature is available.
"""
        password_block_html = f"""
          <div style="margin:22px 0;padding:18px;border:1px solid rgba(255,215,106,0.45);border-radius:16px;background:rgba(255,215,106,0.08);">
            <p style="margin:0 0 8px;color:#ffd76a;font-weight:bold;letter-spacing:1px;text-transform:uppercase;">Temporary Password</p>
            <p style="margin:0;font-size:22px;color:#ffffff;font-weight:bold;">{escape(temporary_password)}</p>
            <p style="margin:10px 0 0;color:#e8d7a1;font-size:14px;line-height:1.5;">
              For security, please log in and change your password when the password reset feature is available.
            </p>
          </div>
        """

    nominee_block_text = ""
    nominee_block_html = ""

    if nominee_url:
        nominee_block_text = f"""

Nominee profile:
{nominee_url}
"""
        nominee_block_html = f"""
          <p style="margin:18px 0 0;">
            <a href="{escape(nominee_url)}" style="display:inline-block;padding:12px 18px;border-radius:999px;border:1px solid rgba(255,215,106,0.75);color:#ffd76a;text-decoration:none;font-weight:bold;">
              View Nominee Profile
            </a>
          </p>
        """

    subject = "You’re Approved: Welcome to ATL’s Hottest Awards"

    text_body = f"""ATL's Hottest Awards

Congratulations {nominee_name}!

Your nominee account has been approved for ATL's Hottest Awards.

You can now log in to your Association Dashboard to review your profile information, update professional details, and prepare for nominee updates.

Login:
{login_url}

Dashboard:
{dashboard_url}

Username:
{username or to_email}
{password_block_text}
{nominee_block_text}

If you did not request this account, please contact ATL's Hottest Awards.

ATL's Hottest Awards
Official Awards • Association • Media Platform
"""

    html_body = f"""
<div style="margin:0;padding:26px;background:#050505;color:#ffffff;font-family:Georgia,'Times New Roman',serif;">
  <div style="max-width:720px;margin:0 auto;border:1px solid rgba(255,215,106,0.75);border-radius:24px;overflow:hidden;background:linear-gradient(135deg,#030303,#35050d 52%,#060606);box-shadow:0 18px 55px rgba(0,0,0,0.55);">
    
    <div style="padding:30px 28px;background:linear-gradient(135deg,#000000,#850817 58%,#000000);border-bottom:1px solid rgba(255,215,106,0.55);">
      <p style="margin:0 0 10px;color:#ffd76a;letter-spacing:3px;text-transform:uppercase;font-weight:bold;font-size:13px;">
        Official Nominee Approval
      </p>
      <h1 style="margin:0;color:#ffffff;font-size:36px;line-height:1.08;">
        Welcome to ATL’s Hottest Awards
      </h1>
      <p style="margin:12px 0 0;color:#f3ddb2;font-size:16px;line-height:1.55;">
        Your nominee account has been approved.
      </p>
    </div>

    <div style="padding:30px 28px;">
      <p style="margin:0 0 18px;font-size:19px;line-height:1.65;color:#ffffff;">
        Congratulations <strong style="color:#ffd76a;">{nominee_name_safe}</strong>!
      </p>

      <p style="margin:0 0 18px;font-size:17px;line-height:1.65;color:#f5f5f5;">
        You are now approved inside the ATL’s Hottest Awards platform. You can log in to your Association Dashboard to review your profile information, update professional details, and prepare for nominee updates.
      </p>

      <div style="margin:22px 0;padding:18px;border:1px solid rgba(255,255,255,0.16);border-radius:16px;background:rgba(255,255,255,0.055);">
        <p style="margin:0 0 8px;color:#ffd76a;font-weight:bold;letter-spacing:1px;text-transform:uppercase;">Account Login</p>
        <p style="margin:0;color:#ffffff;line-height:1.7;">
          <strong>Username:</strong> {username_safe}<br>
          <strong>Email:</strong> {to_email_safe}
        </p>
        {password_block_html}
      </div>

      <div style="margin:24px 0;">
        <a href="{escape(login_url)}" style="display:inline-block;margin:0 10px 12px 0;padding:14px 22px;border-radius:999px;background:#ffd76a;color:#170006;text-decoration:none;font-weight:bold;">
          Log In
        </a>
        <a href="{escape(dashboard_url)}" style="display:inline-block;margin:0 10px 12px 0;padding:14px 22px;border-radius:999px;background:#8f0717;color:#ffffff;text-decoration:none;font-weight:bold;border:1px solid rgba(255,215,106,0.5);">
          Open Dashboard
        </a>
        {nominee_block_html}
      </div>

      <div style="margin:26px 0 0;padding:18px;border-left:4px solid #ffd76a;background:rgba(0,0,0,0.24);border-radius:12px;">
        <p style="margin:0;color:#f2e3bd;font-size:15px;line-height:1.6;">
          Your dashboard is where you can manage professional/member information, nominee updates, profile details, rewards, promos, and future association benefits.
        </p>
      </div>
    </div>

    <div style="padding:20px 28px;border-top:1px solid rgba(255,215,106,0.35);background:#080808;">
      <p style="margin:0;color:#ffd76a;font-weight:bold;">ATL’s Hottest Awards</p>
      <p style="margin:6px 0 0;color:#cfcfcf;font-size:13px;line-height:1.5;">
        Official Awards • Association • Media Platform
      </p>
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
