"""Tests that a raw OIDC access token does not authenticate against the API.

mozilla-django-oidc's DRF authentication class used to be the first of
DEFAULT_AUTHENTICATION_CLASSES, so an access token sent as a bearer token
authenticated on every endpoint that did not override them. It was only checked
by calling the provider's userinfo endpoint: no audience check, so a token
issued to another service of the federation worked here, and no acr claim to
enforce OIDC_REQUIRE_MFA on. The UI never used it (it authenticates with the
session cookie from the login callback) and partners use their API keys.
"""

from django.conf import settings
from django.test.utils import override_settings

import pytest
import responses
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1.0/users/me/"


def userinfo_calls():
    """Requests made to the provider's userinfo endpoint."""
    return [
        call
        for call in responses.calls
        if settings.OIDC_OP_USER_ENDPOINT in call.request.url
    ]


@pytest.mark.parametrize("require_mfa", [True, False])
@responses.activate
def test_api_access_token_does_not_authenticate(require_mfa):
    """A valid access token is not a credential for this API, MFA or not."""

    user = factories.UserFactory()
    responses.add(
        responses.GET,
        settings.OIDC_OP_USER_ENDPOINT,
        json={"sub": user.sub, "email": user.email},
        status=200,
    )

    with override_settings(OIDC_REQUIRE_MFA=require_mfa):
        response = APIClient().get(ME_URL, HTTP_AUTHORIZATION="Bearer an-access-token")

    assert response.status_code == 401
    # Nothing is asked of the provider: the token is not even looked up.
    assert not userinfo_calls()


@responses.activate
def test_unmatched_api_key_is_not_forwarded_to_the_provider():
    """
    An operator API key that no longer matches (rotated, revoked, mistyped) is
    refused locally. It used to fall through to the OIDC authentication class,
    which sent the partner's secret to the provider's userinfo endpoint.
    """

    operator = factories.OperatorFactory()
    responses.add(responses.GET, settings.OIDC_OP_USER_ENDPOINT, json={}, status=200)

    response = APIClient().get(
        f"/api/v1.0/operators/{operator.id}/organizations/",
        HTTP_AUTHORIZATION="Bearer a-partner-key-that-no-longer-matches",
    )

    assert response.status_code == 401
    assert not userinfo_calls()


def test_api_key_still_authenticates():
    """The partner API keys, which share the same header, keep working."""

    operator = factories.OperatorFactory(
        external_management_api_key="a-valid-partner-key"
    )

    response = APIClient().get(
        f"/api/v1.0/operators/{operator.id}/organizations/",
        HTTP_AUTHORIZATION="Bearer a-valid-partner-key",
    )

    assert response.status_code == 200
