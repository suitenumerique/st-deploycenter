"""Authentication URLs for the People core app."""

from django.urls import path

from mozilla_django_oidc.urls import urlpatterns as mozzila_oidc_urls

from .views import (
    OIDCAuthenticationRequestView,
    OIDCLogoutCallbackView,
    OIDCLogoutView,
)

# Filter out any conflicting logout and authentication URLs from Mozilla OIDC
filtered_mozilla_urls = [
    url
    for url in mozzila_oidc_urls
    if not any(name in str(url) for name in ["oidc_logout", "oidc_authentication_init"])
]

urlpatterns = [
    # Override the default 'authenticate/' path, keeping its route and name, to
    # request multi-factor authentication (see OIDC_REQUIRE_MFA).
    path(
        "authenticate/",
        OIDCAuthenticationRequestView.as_view(),
        name="oidc_authentication_init",
    ),
    # Override the default 'logout/' path from Mozilla Django OIDC with our custom view.
    path("logout/", OIDCLogoutView.as_view(), name="oidc_logout_custom"),
    path(
        "logout-callback/",
        OIDCLogoutCallbackView.as_view(),
        name="oidc_logout_callback",
    ),
    *filtered_mozilla_urls,
]
