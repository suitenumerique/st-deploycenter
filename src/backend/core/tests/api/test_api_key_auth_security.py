"""Regression tests for the empty-key authentication bypass.

``secrets.compare_digest("", "")`` is True, and ``"Bearer ".split(" ", 1)`` yields an
empty token — so any key mechanism that compares a presented token against an
unconfigured (empty) expected value authenticates whoever sends an empty bearer token.

Only the entitlements API was actually exploitable: ``config.get(...)`` defaults to
``""`` and the key is written solely by the admin's "Generate API Key" button, so
every service that never had one accepted an empty token.

The other two mechanisms are covered as defence in depth, not because they were
reachable — neither can hold an empty key today. The admin stores NULL in
``external_management_api_key`` (``CharField.formfield()`` sets ``empty_value=None``
when the field is ``null=True``) and NULL never matches the lookup, while
``ListValue`` drops empty entries when parsing ``SERVER_TO_SERVER_API_TOKENS``. These
tests pin that a row or setting holding ``""`` — from a fixture, a bulk update, an
import — still cannot be used as a credential.
"""

from django.contrib.admin.sites import site
from django.test import override_settings

import pytest
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient

from core import factories, models
from core.authentication import ServerToServerAuthentication

pytestmark = pytest.mark.django_db

ENTITLEMENTS_ENDPOINT = "/api/v1.0/entitlements/"

# What an attacker sends: a well-formed header carrying nothing.
EMPTY_BEARER = "Bearer "


def _entitlements_setup(config):
    """An organization subscribed to a service holding ``config``."""
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="test_service", config=config)
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator, is_active=True
    )
    return organization, service


def _entitlements_params(organization, service):
    return {
        "service_id": service.id,
        "account_type": "user",
        "account_id": "xyz",
        "siret": organization.siret,
    }


# --- entitlements API (X-Service-Auth) ---------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        # The state every service is created in: nobody generated a key.
        {},
        # Configured for metrics, but still no entitlements key.
        {"metrics_endpoint": "https://example.invalid/"},
        # Explicitly empty, and explicitly null.
        {"entitlements_api_key": ""},
        {"entitlements_api_key": None},
        None,
    ],
)
def test_entitlements_refuses_empty_token_when_no_key_is_configured(config):
    """An empty bearer token must not match a service that has no key."""
    organization, service = _entitlements_setup(config)

    response = APIClient().get(
        ENTITLEMENTS_ENDPOINT,
        query_params=_entitlements_params(organization, service),
        headers={"X-Service-Auth": EMPTY_BEARER},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("config", [{}, {"entitlements_api_key": ""}, None])
def test_entitlements_refuses_any_token_when_no_key_is_configured(config):
    """A service without a key authenticates nobody, whatever they send."""
    organization, service = _entitlements_setup(config)

    for token in ("Bearer anything", "Bearer None", EMPTY_BEARER):
        response = APIClient().get(
            ENTITLEMENTS_ENDPOINT,
            query_params=_entitlements_params(organization, service),
            headers={"X-Service-Auth": token},
        )
        assert response.status_code == 401, token


def test_entitlements_null_config_does_not_crash():
    """``config`` is nullable: reading the key off None must not be a 500."""
    organization, service = _entitlements_setup(None)

    response = APIClient().get(
        ENTITLEMENTS_ENDPOINT,
        query_params=_entitlements_params(organization, service),
        headers={"X-Service-Auth": "Bearer whatever"},
    )
    assert response.status_code == 401


def test_entitlements_refuses_an_empty_token_against_a_real_key():
    """The presented token being empty is refused even when a key exists."""
    organization, service = _entitlements_setup({"entitlements_api_key": "s3cret"})

    response = APIClient().get(
        ENTITLEMENTS_ENDPOINT,
        query_params=_entitlements_params(organization, service),
        headers={"X-Service-Auth": EMPTY_BEARER},
    )
    assert response.status_code == 401


def test_entitlements_still_accepts_the_configured_key():
    """The fix must not break the legitimate path."""
    organization, service = _entitlements_setup({"entitlements_api_key": "s3cret"})

    response = APIClient().get(
        ENTITLEMENTS_ENDPOINT,
        query_params=_entitlements_params(organization, service),
        headers={"X-Service-Auth": "Bearer s3cret"},
    )
    assert response.status_code == 200


# --- external management API keys (Operator and Service) ---------------------


def test_external_management_refuses_empty_token_against_a_stored_empty_key():
    """A row holding "" must not be usable as a credential.

    Not a state the admin creates — it saves NULL — so this guards against a fixture
    or a bulk update putting an empty string there.
    """
    operator = factories.OperatorFactory(external_management_api_key="")
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    response = APIClient().get(
        f"/api/v1.0/operators/{operator.id}/organizations/",
        headers={"Authorization": EMPTY_BEARER},
    )
    assert response.status_code == 401


def test_external_management_still_accepts_a_real_key():
    """The fix must not break the legitimate path."""
    operator = factories.OperatorFactory(external_management_api_key="a-real-key")
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    response = APIClient().get(
        f"/api/v1.0/operators/{operator.id}/organizations/",
        headers={"Authorization": "Bearer a-real-key"},
    )
    assert response.status_code == 200


# --- server-to-server static tokens ------------------------------------------


@pytest.mark.parametrize("tokens", [[], [""], ["", "real-token"]])
def test_server_to_server_refuses_an_empty_token(tokens):
    """An empty entry in the configured list must not become a valid credential."""

    class _Request:  # pylint: disable=too-few-public-methods
        headers = {"Authorization": EMPTY_BEARER}

    with override_settings(SERVER_TO_SERVER_API_TOKENS=tokens):
        with pytest.raises(AuthenticationFailed):
            ServerToServerAuthentication().authenticate(_Request())


def test_server_to_server_still_accepts_a_configured_token():
    """The fix must not break the legitimate path."""

    class _Request:  # pylint: disable=too-few-public-methods
        headers = {"Authorization": "Bearer real-token"}

    with override_settings(SERVER_TO_SERVER_API_TOKENS=["", "real-token"]):
        assert ServerToServerAuthentication().authenticate(_Request()) is None


def test_admin_stores_null_not_empty_string_for_a_blank_key():
    """Pins why the previous test is defence in depth rather than a live hole.

    A blank key in the admin must keep saving NULL: were it ever to save "", the
    unique constraint would also stop at one such row, hiding the problem.
    """
    model_admin = site._registry[models.Operator]  # pylint: disable=protected-access
    form_class = model_admin.get_form(request=None)
    form = form_class(
        data={
            "name": "Opérateur",
            "url": "https://operateur.invalid/",
            "scope": "departement",
            "external_management_api_key": "",
        }
    )
    assert form.is_valid(), form.errors
    operator = form.save()

    stored = models.Operator.objects.get(pk=operator.pk).external_management_api_key
    assert stored is None
