"""Unit tests for the authentication middlewares."""

from django.test.utils import override_settings

import pytest
from rest_framework.test import APIClient

from core import factories
from core.authentication.backends import MFA_ACR_SESSION_KEY

pytestmark = pytest.mark.django_db

OIDC_BACKEND = "core.authentication.backends.OIDCAuthenticationBackend"
ME_URL = "/api/v1.0/users/me/"


def oidc_client(acr=None):
    """Return a client holding an OIDC session, with the given acr if any."""
    client = APIClient()
    client.force_login(factories.UserFactory(), backend=OIDC_BACKEND)

    if acr is not None:
        session = client.session
        session[MFA_ACR_SESSION_KEY] = acr
        session.save()

    return client


@override_settings(OIDC_REQUIRE_MFA=True)
def test_middleware_ends_session_opened_before_mfa_was_required():
    """A session opened without a second factor is closed on its next request."""

    client = oidc_client()

    assert client.get(ME_URL).status_code == 401
    # The session is gone, not just refused once.
    assert client.get(ME_URL).status_code == 401


@override_settings(OIDC_REQUIRE_MFA=True)
@pytest.mark.parametrize("acr", ["eidas0-mfa", "eidas1-mfa", "eidas2", "eidas3"])
def test_middleware_keeps_session_authenticated_with_a_second_factor(acr):
    """A session carrying an accepted acr goes through."""

    assert oidc_client(acr).get(ME_URL).status_code == 200


@override_settings(OIDC_REQUIRE_MFA=True, OIDC_MFA_ACR_VALUES=["eidas2", "eidas3"])
def test_middleware_ends_session_when_acr_values_are_narrowed():
    """Narrowing the accepted values closes the sessions below the new bar."""

    assert oidc_client("eidas1-mfa").get(ME_URL).status_code == 401


@override_settings(OIDC_REQUIRE_MFA=False)
def test_middleware_keeps_sessions_when_mfa_is_not_required():
    """With the setting off, sessions without an acr are left alone."""

    assert oidc_client().get(ME_URL).status_code == 200


@override_settings(OIDC_REQUIRE_MFA=True)
def test_middleware_keeps_sessions_opened_outside_oidc():
    """A password login on the Django admin never gets an acr claim."""

    client = APIClient()
    client.force_login(
        factories.UserFactory(), backend="django.contrib.auth.backends.ModelBackend"
    )

    assert client.get(ME_URL).status_code == 200


@override_settings(OIDC_REQUIRE_MFA=True)
def test_middleware_leaves_anonymous_requests_alone():
    """No session, nothing to close."""

    assert APIClient().get(ME_URL).status_code == 401
