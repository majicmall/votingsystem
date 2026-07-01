# ballot/views.py
from __future__ import annotations

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST


@require_http_methods(["GET"])
def ballot_view(request):
    return HttpResponse(
        """
        <h1>ATL’s Hottest Ballot</h1>
        <p>Ballot rebuild scaffold is active.</p>
        <p>Next step: models, admin, forms, services, and full templates.</p>
        """
    )


@require_http_methods(["POST"])
@csrf_protect
def submit_votes(request):
    return JsonResponse(
        {
            "message": "Voting endpoint scaffold is active. Full vote logic will be restored next.",
            "saved": [],
            "errors": [],
        }
    )


@require_http_methods(["GET", "POST"])
@csrf_protect
def signup(request):
    return HttpResponse("<h1>Signup scaffold</h1><p>Full signup flow coming next.</p>")


@require_http_methods(["GET", "POST"])
@csrf_protect
def nominee_upload(request, token):
    return HttpResponse(f"<h1>Nominee upload scaffold</h1><p>Token: {token}</p>")


@require_http_methods(["GET", "POST"])
@csrf_protect
def association_join(request):
    return HttpResponse("<h1>Association join scaffold</h1><p>Full nominee request flow coming next.</p>")


@require_http_methods(["GET"])
@login_required
def association_dashboard(request):
    return HttpResponse("<h1>Association dashboard scaffold</h1><p>Full nominee dashboard coming next.</p>")


@require_http_methods(["GET", "POST"])
@login_required
@csrf_protect
def association_nominee_edit(request, nominee_id):
    return HttpResponse(f"<h1>Edit nominee scaffold</h1><p>Nominee: {nominee_id}</p>")


@require_http_methods(["POST"])
@login_required
@csrf_protect
def association_nominee_regen_link(request, nominee_id):
    return redirect("assoc_dashboard")


@require_http_methods(["GET", "POST"])
@login_required
@csrf_protect
def request_categories(request, nominee_id):
    return HttpResponse(f"<h1>Request categories scaffold</h1><p>Nominee: {nominee_id}</p>")


@require_POST
@login_required
@csrf_protect
def association_nominee_delete(request, nominee_id):
    return redirect("assoc_dashboard")


@require_http_methods(["GET", "POST"])
@csrf_protect
def nominee_signup(request):
    return HttpResponse("<h1>Nominee signup scaffold</h1><p>Full nominee signup flow coming next.</p>")


@staff_member_required
def staff_dashboard(request):
    return HttpResponse("<h1>Staff dashboard scaffold</h1><p>Full approval tools coming next.</p>")


@require_http_methods(["POST"])
@staff_member_required
@csrf_protect
def staff_request_approve(request, req_id):
    return redirect("staff_dashboard")


@require_http_methods(["POST"])
@staff_member_required
@csrf_protect
def staff_request_deny(request, req_id):
    return redirect("staff_dashboard")


@require_http_methods(["GET"])
@staff_member_required
def tallies_json(request):
    return JsonResponse({"generated_at": None, "categories": []})


@require_http_methods(["GET"])
@staff_member_required
def export_votes_csv(request):
    return HttpResponse("category_slug,category_name,nominee_id,nominee_name,votes\n", content_type="text/csv")


@require_http_methods(["GET", "POST"])
@csrf_protect
def upload_test(request):
    return HttpResponse("<h1>Upload test scaffold</h1>")


@require_http_methods(["GET", "POST"])
def logout_then_home(request):
    logout(request)
    return redirect("/")
