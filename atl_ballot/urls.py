# atl_ballot/urls.py

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, re_path
from django.views.generic import RedirectView

from ballot import views as ballot_views


urlpatterns = [
    path("events/live/<slug:slug>/qr.png", ballot_views.event_qr_code, name="event_qr_code"),

    path("events/live/<slug:slug>/", ballot_views.event_detail, name="event_detail"),

    path("events/submitted/<slug:slug>/", ballot_views.event_submitted, name="event_submitted"),

    path("events/sample/<slug:slug>/", ballot_views.sample_event_detail, name="sample_event_detail"),

    path("events/whats-happening/", ballot_views.events_whats_happening, name="events_whats_happening"),
    path("events/submit/", ballot_views.event_submit, name="event_submit"),

    path("about-atls-hottest/", ballot_views.about_atls_hottest, name="about_atls_hottest"),
    path("memberships/", ballot_views.membership_plans, name="membership_plans"),
    path("memberships/<slug:slug>/", ballot_views.membership_plan_detail, name="membership_plan_detail"),
    path("memberships/choose/<slug:slug>/", ballot_views.choose_membership_plan, name="choose_membership_plan"),
    re_path(r"^memberships/pay/(?P<slug>[-a-zA-Z0-9_]+)/$", ballot_views.membership_payment_center, name="membership_payment_center"),
    path("membership/dashboard/", ballot_views.membership_dashboard, name="membership_dashboard"),
    path("marketplace/", ballot_views.atls_hottest_marketplace, name="atls_hottest_marketplace"),
    path("advertise/", ballot_views.advertise_command_center, name="advertise_command_center"),
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