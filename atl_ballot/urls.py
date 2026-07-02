# atl_ballot/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from ballot import views as ballot_views

urlpatterns = [
    # Landing page
    path("", ballot_views.landing_page, name="home"),

    # Ballot
    path("ballot/", ballot_views.ballot_view, name="ballot"),
    path("submit-votes/", ballot_views.submit_votes, name="submit_votes"),

    # Accounts
    path("accounts/signup/", ballot_views.signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="ballot/login.html"), name="login"),
    path("accounts/logout/", ballot_views.logout_then_home, name="logout"),
    path("accounts/logout-then-home/", ballot_views.logout_then_home, name="logout_then_home"),

    # Nominee signup MUST come before nominee detail
    path("nominee/signup/", ballot_views.nominee_signup, name="nominee_signup"),

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
