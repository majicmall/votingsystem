from django.urls import path

from . import views

app_name = "megaverse"

urlpatterns = [
    path("link/start/", views.start_link, name="link_start"),
    path("link/callback/", views.link_callback, name="link_callback"),
    path("link/result/", views.link_result, name="link_result"),
]
