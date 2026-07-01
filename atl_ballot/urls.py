# atl_ballot/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from ballot import views as ballot_views

urlpatterns = [
    # Public ballot
    path("", ballot_views.ballot_view, name="home"),
    path("ballot/", ballot_views.ballot_view, name="ballot"),
    path("submit-votes/", ballot_views.submit_votes, name="submit_votes"),

    # Accounts
    path("accounts/signup/", ballot_views.signup, name="signup"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="ballot/login.html"),
        name="login",
    ),
    path("accounts/logout/", ballot_views.logout_then_home, name="logout"),
    path("accounts/logout-then-home/", ballot_views.logout_then_home, name="logout_then_home"),

    # Password reset
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="ballot/password_reset_form.html",
            email_template_name="ballot/password_reset_email.txt",
            success_url="/accounts/password-reset/done/",
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="ballot/password_reset_done.html",
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
            template_name="ballot/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # Nominee public upload
    path("u/<uuid:token>/", ballot_views.nominee_upload, name="nominee_upload"),

    # Association / nominee manager
    path("association/join/", ballot_views.association_join, name="assoc_join"),
    path("association/dashboard/", ballot_views.association_dashboard, name="assoc_dashboard"),
    path(
        "association/nominee/<slug:nominee_id>/edit/",
        ballot_views.association_nominee_edit,
        name="assoc_nominee_edit",
    ),
    path(
        "association/nominee/<slug:nominee_id>/regen-link/",
        ballot_views.association_nominee_regen_link,
        name="assoc_nominee_regen_link",
    ),
    path(
        "association/nominee/<slug:nominee_id>/request-categories/",
        ballot_views.request_categories,
        name="request_categories",
    ),
    path(
        "association/nominee/<slug:nominee_id>/delete/",
        ballot_views.association_nominee_delete,
        name="assoc_nominee_delete",
    ),
    path("nominee/signup/", ballot_views.nominee_signup, name="nominee_signup"),

    # Staff
    path("staff/", ballot_views.staff_dashboard, name="staff_dashboard"),
    path(
        "staff/requests/<int:req_id>/approve/",
        ballot_views.staff_request_approve,
        name="staff_request_approve",
    ),
    path(
        "staff/requests/<int:req_id>/deny/",
        ballot_views.staff_request_deny,
        name="staff_request_deny",
    ),
    path("staff/tallies.json", ballot_views.tallies_json, name="tallies_json"),
    path("staff/export.csv", ballot_views.export_votes_csv, name="export_votes_csv"),

    # Debug helper
    path("upload-test/", ballot_views.upload_test, name="upload_test"),

    # Admin
    path("admin/logout/", ballot_views.logout_then_home, name="admin_logout"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)