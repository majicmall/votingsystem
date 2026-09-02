from django.views.static import serve as django_static_serve
# atl_ballot/urls.py

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, re_path
from django.views.generic import RedirectView, TemplateView

from ballot import views as ballot_views


urlpatterns = [
    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="robots.txt",
            content_type="text/plain",
        ),
    ),

    path("events/live/<slug:slug>/qr.png", ballot_views.event_qr_code, name="event_qr_code"),

    path("events/live/<slug:slug>/", ballot_views.event_detail, name="event_detail"),
    path(
        "events/live/<slug:slug>/promote/",
        ballot_views.event_promote,
        name="event_promote",
    ),

    # Secure producer event-promotion payment flow
    path(
        "events/promotions/<uuid:token>/payment/",
        ballot_views.event_promotion_payment,
        name="event_promotion_payment",
    ),
    path(
        "events/promotions/<uuid:token>/checkout/",
        ballot_views.event_promotion_checkout,
        name="event_promotion_checkout",
    ),
    path(
        "events/promotions/<uuid:token>/success/",
        ballot_views.event_promotion_payment_success,
        name="event_promotion_payment_success",
    ),
    path(
        "events/promotions/<uuid:token>/cancel/",
        ballot_views.event_promotion_payment_cancel,
        name="event_promotion_payment_cancel",
    ),
    path(
        "payments/stripe/event-promotions/webhook/",
        ballot_views.stripe_event_promotion_webhook,
        name="stripe_event_promotion_webhook",
    ),

    path("events/submitted/<slug:slug>/", ballot_views.event_submitted, name="event_submitted"),

    path("events/sample/<slug:slug>/", ballot_views.sample_event_detail, name="sample_event_detail"),

    path("events/whats-happening/", ballot_views.events_whats_happening, name="events_whats_happening"),
    path("events/submit/", ballot_views.event_submit, name="event_submit"),

    # Staff-only Mobile Event Approval Center

    path(
        "events/admin/promotions/<int:pk>/action/",
        ballot_views.event_promotion_order_action,
        name="event_promotion_order_action",
    ),

    path(
        "events/admin/approvals/",
        ballot_views.event_approval_center,
        name="event_approval_center",
    ),
    path(
        "events/admin/approvals/<int:pk>/action/",
        ballot_views.event_approval_action,
        name="event_approval_action",
    ),

    path("about-atls-hottest/", ballot_views.about_atls_hottest, name="about_atls_hottest"),
    path("memberships/", ballot_views.membership_plans, name="membership_plans"),
    path("memberships/<slug:slug>/", ballot_views.membership_plan_detail, name="membership_plan_detail"),
    path("memberships/choose/<slug:slug>/", ballot_views.choose_membership_plan, name="choose_membership_plan"),
    re_path(r"^memberships/pay/(?P<slug>[-a-zA-Z0-9_]+)/$", ballot_views.membership_payment_center, name="membership_payment_center"),
    path("membership/dashboard/", ballot_views.membership_dashboard, name="membership_dashboard"),
    path("marketplace/", ballot_views.atls_hottest_marketplace, name="atls_hottest_marketplace"),
    path("advertise/", ballot_views.advertise_command_center, name="advertise_command_center"),
    path("advertise/click/<int:ad_id>/", ballot_views.billboard_click, name="billboard_click"),
    path("advertise/thank-you/", ballot_views.advertise_thank_you, name="advertise_thank_you"),

    path("tv/", ballot_views.atl_tv, name="atl_tv"),
    path("favicon.ico", RedirectView.as_view(url=settings.STATIC_URL + "ballot/favicon.svg", permanent=True)),
    path("healthz/", ballot_views.healthz, name="healthz"),

    # Landing page
    path("", ballot_views.landing_page, name="home"),

    # Ballot
    path("ballot/", ballot_views.ballot_view, name="ballot"),
    re_path(r"^ballot/category/(?P<category_slug>[-a-zA-Z0-9_]+)/$", ballot_views.ballot_category_view, name="ballot_category"),
    re_path(r"^ballot/select/(?P<category_slug>[-a-zA-Z0-9_]+)/(?P<nominee_id>[-a-zA-Z0-9_]+)/$", ballot_views.select_ballot_nominee, name="select_ballot_nominee"),
    path("ballot/review/", ballot_views.ballot_review, name="ballot_review"),
    path("ballot/submit-final/", ballot_views.submit_final_ballot, name="submit_final_ballot"),
    path("ballot/confirmation/", ballot_views.ballot_confirmation, name="ballot_confirmation"),
    path("submit-votes/", ballot_views.submit_votes, name="submit_votes"),

    # Accounts
    path("accounts/signup/", ballot_views.signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="ballot/login.html"), name="login"),

    # Secure password recovery
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="ballot/password_reset_form.html",
            email_template_name="ballot/password_reset_email.txt",
            subject_template_name="ballot/password_reset_subject.txt",
            success_url="/accounts/password-reset/done/",
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="ballot/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="ballot/password_reset_confirm.html",
            success_url="/accounts/reset/done/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="ballot/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("accounts/logout/", ballot_views.logout_then_home, name="logout"),
    path("accounts/logout-then-home/", ballot_views.logout_then_home, name="logout_then_home"),

    # Nominee signup MUST come before nominee detail
    path("nominee/signup/", ballot_views.nominee_signup, name="nominee_signup"),
    path("nomination/thank-you/", ballot_views.nomination_thank_you, name="nomination_thank_you"),
    path("nomination/thank-you/<slug:nominee_id>/", ballot_views.nomination_thank_you, name="nomination_thank_you_detail"),

    # Nominee public upload
    path("u/<uuid:token>/", ballot_views.nominee_upload, name="nominee_upload"),

    # Association / nominee manager
    path("association/signup/", ballot_views.association_signup, name="association_signup"),
    path("association/join/", ballot_views.association_join, name="assoc_join"),
    path("association/dashboard/", ballot_views.association_dashboard, name="assoc_dashboard"),
    path("association/nominee/<slug:nominee_id>/edit/", ballot_views.association_nominee_edit, name="assoc_nominee_edit"),
    path("association/nominee/<slug:nominee_id>/regen-link/", ballot_views.association_nominee_regen_link, name="assoc_nominee_regen_link"),
    path("association/nominee/<slug:nominee_id>/request-categories/", ballot_views.request_categories, name="request_categories"),
    path("association/nominee/<slug:nominee_id>/delete/", ballot_views.association_nominee_delete, name="assoc_nominee_delete"),

    # Staff
    path("staff/", ballot_views.staff_dashboard, name="staff_dashboard"),
    path("staff/requests/<int:req_id>/approve/", ballot_views.staff_request_approve, name="staff_request_approve"),
    path("staff/requests/<int:req_id>/deny/", ballot_views.staff_request_deny, name="staff_request_deny"),
    path("staff/tallies.json", ballot_views.tallies_json, name="tallies_json"),
    path("staff/export.csv", ballot_views.export_votes_csv, name="export_votes_csv"),

    path("upload-test/", ballot_views.upload_test, name="upload_test"),

    # Nominee detail MUST stay after nominee/signup/
    path("nominee/<slug:nominee_id>/", ballot_views.nominee_detail, name="nominee_detail"),
    path("nominee/<slug:nominee_id>/vote/", ballot_views.vote_nominee, name="vote_nominee"),

    # Admin
    path("admin/logout/", ballot_views.logout_then_home, name="admin_logout"),
    path("admin/", admin.site.urls),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# Temporary production media serving for uploaded event flyers.
# Later, move uploads to Cloudinary, S3, or Render Persistent Disk.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", django_static_serve, {"document_root": settings.MEDIA_ROOT}),
]
