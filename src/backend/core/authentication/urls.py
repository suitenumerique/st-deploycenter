"""Authentication URLs for the People core app."""

from django.urls import path

from mozilla_django_oidc.urls import urlpatterns as mozzila_oidc_urls

from .views import OIDCLogoutCallbackView, OIDCLogoutView

# Filter out any conflicting logout URLs from Mozilla OIDC
filtered_mozilla_urls = [
    url
    for url in mozzila_oidc_urls
    if not any(name in str(url) for name in ["oidc_logout"])
]

urlpatterns = [
    # Override the default 'logout/' path from Mozilla Django OIDC with our custom view.
    path("logout/", OIDCLogoutView.as_view(), name="oidc_logout_custom"),
    path(
        "logout-callback/",
        OIDCLogoutCallbackView.as_view(),
        name="oidc_logout_callback",
    ),
    *filtered_mozilla_urls,
]
