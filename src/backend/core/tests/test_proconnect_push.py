"""
Tests for the ProConnect api-partenaires domains push (core/proconnect.py).
"""

import hashlib
import hmac
import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

import pytest
import requests
import responses
from rest_framework.test import APIClient

from core import factories
from core.models import ServiceSubscription
from core.services.locks import advisory_lock_key
from core.services.proconnect import (
    ProConnectPartnersClient,
    ProConnectPartnersError,
    idp_routed_domains,
    redact_credentials,
    sign_request,
    subscription_idp_id,
    sync_proconnect_provider,
)
from core.signals import suppress_proconnect_sync

pytestmark = pytest.mark.django_db

BASE_URL = "https://api-partenaires-sandbox.test"
SECRET = "test-oidc-providers-secret"
IDP = "aaa58fc5-0397-495d-8cb5-92b02559d376"

proconnect_settings = override_settings(
    PROCONNECT_API_PARTENAIRES_URL=BASE_URL,
    PROCONNECT_API_PARTENAIRES_SECRET=SECRET,
)


def _expected_signature(method, path, timestamp, body=None):
    """Recompute the signature the same way the api-partenaires middleware does."""
    if isinstance(body, bytes):
        # The wire body is utf-8 bytes; the signature is over the same text.
        body = body.decode("utf-8")
    message = f"{timestamp}:{method}:{path}?"
    if body:
        message += f":{body}"
    return hmac.new(
        SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _make_proconnect_subscription(
    idp_id, domains, is_active=True, config_override=None
):
    """Create an active ProConnect subscription resolving to ``idp_id``.

    Suppresses the synchronous push so the factory setup doesn't hit the API.
    """
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": idp_id})
    factories.OperatorServiceConfigFactory(
        operator=operator,
        service=service,
        config_override=config_override or {},
    )
    with suppress_proconnect_sync():
        return factories.ServiceSubscriptionFactory(
            organization=organization,
            service=service,
            operator=operator,
            metadata={"domains": domains},
            is_active=is_active,
        )


# --- signature ---------------------------------------------------------------


def test_sign_request_matches_middleware_format():
    """The signed message matches the api-partenaires format (no body)."""
    timestamp, signature = sign_request(
        SECRET, "GET", f"/api/oidc_providers/{IDP}/configuration", "", None
    )
    assert signature == _expected_signature(
        "GET", f"/api/oidc_providers/{IDP}/configuration", timestamp
    )


def test_sign_request_includes_body():
    """When a body is present, it is appended to the signed message."""
    body = '{"attached_email_domains":["a.fr"]}'
    timestamp, signature = sign_request(
        SECRET, "PATCH", f"/api/oidc_providers/{IDP}/configuration", "", body
    )
    assert signature == _expected_signature(
        "PATCH", f"/api/oidc_providers/{IDP}/configuration", timestamp, body
    )


# --- client ------------------------------------------------------------------


@responses.activate
def test_client_set_attached_email_domains_sends_signed_patch():
    """The PATCH is signed over the exact bytes sent."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "name": "test", "attached_email_domains": ["a.fr", "b.fr"]},
        status=200,
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    result = client.set_attached_email_domains(IDP, ["a.fr", "b.fr"])
    assert result["attached_email_domains"] == ["a.fr", "b.fr"]

    request = responses.calls[0].request
    body = request.body
    assert json.loads(body) == {"attached_email_domains": ["a.fr", "b.fr"]}
    # The signature in the header must validate against the exact body sent.
    expected = _expected_signature(
        "PATCH",
        f"/api/oidc_providers/{IDP}/configuration",
        request.headers["X-Timestamp"],
        body,
    )
    assert request.headers["X-Signature"] == expected
    assert request.headers["Content-Type"] == "application/json"


@responses.activate
def test_client_raises_on_error_status():
    """A 4xx/5xx response raises ProConnectPartnersError."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"error": "attached_email_domain_not_allowed"},
        status=422,
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    with pytest.raises(ProConnectPartnersError):
        client.set_attached_email_domains(IDP, ["evil.fr"])


@responses.activate
def test_client_error_carries_structured_domain_not_allowed():
    """The error exposes api-partenaires' error code + offending domains."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={
            "error": "attached_email_domain_not_allowed",
            "attached_email_domains": ["evil.fr", "bad.fr"],
        },
        status=422,
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    with pytest.raises(ProConnectPartnersError) as excinfo:
        client.set_attached_email_domains(IDP, ["evil.fr", "bad.fr"])
    assert excinfo.value.status_code == 422
    assert excinfo.value.error_code == "attached_email_domain_not_allowed"
    assert excinfo.value.domains == ["evil.fr", "bad.fr"]


def test_client_routes_through_proxy_when_configured():
    """A configured proxy_url is passed to requests for both http and https."""
    client = ProConnectPartnersClient(
        base_url=BASE_URL,
        secret=SECRET,
        proxy_url="socks5://user:pass@proxy:1080",
    )
    fake = mock.Mock(status_code=200, text="{}")
    fake.json.return_value = {"attached_email_domains": []}
    with mock.patch(
        "core.services.proconnect.requests.request", return_value=fake
    ) as request_mock:
        client.get_configuration(IDP)

    _, kwargs = request_mock.call_args
    assert kwargs["proxies"] == {
        "http": "socks5://user:pass@proxy:1080",
        "https": "socks5://user:pass@proxy:1080",
    }


def test_client_no_proxy_by_default():
    """With no proxy configured, requests gets proxies=None (direct)."""
    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    fake = mock.Mock(status_code=200, text="{}")
    fake.json.return_value = {}
    with mock.patch(
        "core.services.proconnect.requests.request", return_value=fake
    ) as request_mock:
        client.get_configuration(IDP)

    _, kwargs = request_mock.call_args
    assert kwargs["proxies"] is None


def test_client_not_configured():
    """An unconfigured client reports it and refuses to call."""
    client = ProConnectPartnersClient(base_url="", secret="")
    assert client.is_configured is False
    with pytest.raises(ProConnectPartnersError):
        client.get_configuration(IDP)


# --- idp_routed_domains -------------------------------------------------------


def test_idp_routed_domains_unions_across_active_subscriptions():
    """Domains from all active subscriptions for the idp are unioned + normalized."""
    _make_proconnect_subscription(IDP, ["b.fr", "a.fr"])
    _make_proconnect_subscription(IDP, ["A.fr ", "c.fr"])  # dup + case/space
    # A different idp must not leak in.
    _make_proconnect_subscription("other-idp", ["z.fr"])
    # Inactive subscription must be ignored.
    _make_proconnect_subscription(IDP, ["inactive.fr"], is_active=False)

    assert idp_routed_domains(IDP) == ["a.fr", "b.fr", "c.fr"]


def test_idp_routed_domains_respects_operator_override():
    """idp_id resolution uses the operator's effective config override."""
    subscription = _make_proconnect_subscription(
        "base-idp", ["a.fr"], config_override={"idp_id": "override-idp"}
    )
    assert subscription_idp_id(subscription) == "override-idp"
    assert idp_routed_domains("override-idp") == ["a.fr"]
    assert idp_routed_domains("base-idp") == []


# --- sync_proconnect_provider ------------------------------------------------


@proconnect_settings
@responses.activate
def test_sync_provider_pushes_full_list():
    """sync PATCHes the full union of active-subscription domains (single call)."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "attached_email_domains": ["a.fr", "b.fr"]},
        status=200,
    )

    result = sync_proconnect_provider(IDP)
    assert result["success"] is True
    assert result["domains"] == ["a.fr", "b.fr"]
    assert len(responses.calls) == 1  # no verify GET, just the PATCH
    assert responses.calls[0].request.method == "PATCH"
    assert json.loads(responses.calls[0].request.body) == {
        "attached_email_domains": ["a.fr", "b.fr"]
    }


@proconnect_settings
@responses.activate
def test_sync_provider_swallows_api_errors():
    """A failing push is reported but never raises."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(responses.PATCH, url, json={"error": "boom"}, status=500)

    result = sync_proconnect_provider(IDP)
    assert result["success"] is False
    assert "500" in result["error"]


@proconnect_settings
@responses.activate
def test_sync_provider_takes_a_per_idp_advisory_lock():
    """The read + PATCH + commit run under a lock keyed on the idp, so two
    concurrent pushes can't each compute a set and clobber the other's."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    responses.add(
        responses.PATCH,
        f"{BASE_URL}/api/oidc_providers/{IDP}/configuration",
        json={"uid": IDP, "attached_email_domains": ["a.fr"]},
        status=200,
    )

    with CaptureQueriesContext(connection) as ctx:
        assert sync_proconnect_provider(IDP)["success"] is True

    locks = [q for q in ctx.captured_queries if "pg_advisory_xact_lock" in q["sql"]]
    assert len(locks) == 1
    # The key is a pure function of the idp, so two processes pushing the same
    # provider derive the same one. Pinned to a literal: a salted or otherwise
    # per-process key would still pass an `f(x) == f(x)` assertion.
    assert advisory_lock_key(IDP) == -6099780878716515827
    assert str(advisory_lock_key(IDP)) in locks[0]["sql"]
    assert advisory_lock_key("other-idp") != advisory_lock_key(IDP)


def test_sync_provider_skips_when_not_configured():
    """With no secret/url configured, sync is skipped (no HTTP call)."""
    with override_settings(
        PROCONNECT_API_PARTENAIRES_URL="", PROCONNECT_API_PARTENAIRES_SECRET=""
    ):
        result = sync_proconnect_provider(IDP)
    assert result["skipped"] is True


# --- management command ------------------------------------------------------


@proconnect_settings
@responses.activate
def test_management_command_pushes_all_providers():
    """The backfill command discovers active providers and pushes each."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "attached_email_domains": ["a.fr"]},
        status=200,
    )

    out = StringIO()
    call_command("proconnect_sync", stdout=out)
    assert "OK" in out.getvalue()
    assert IDP in out.getvalue()


def test_management_command_dry_run_makes_no_calls():
    """--dry-run prints the domains without needing configuration or HTTP."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr"])
    out = StringIO()
    with override_settings(
        PROCONNECT_API_PARTENAIRES_URL="", PROCONNECT_API_PARTENAIRES_SECRET=""
    ):
        call_command("proconnect_sync", "--dry-run", stdout=out)
    assert "[dry-run]" in out.getvalue()
    assert "a.fr" in out.getvalue()


# --- rollback on push failure (in-transaction sync) --------------------------


@proconnect_settings
@responses.activate
def test_subscription_activation_rolls_back_on_push_failure():
    """A failed api-partenaires push rolls back the activation and returns 502."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(responses.PATCH, url, json={"error": "boom"}, status=500)

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": IDP})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 502
    # The activation was rolled back — no subscription persisted.
    assert not ServiceSubscription.objects.filter(
        service=service, organization=organization
    ).exists()


# --- signature golden vectors ------------------------------------------------


def test_sign_request_matches_known_vectors():
    """Golden vectors: digests precomputed *independently* (openssl) against the
    api-partenaires signature format — pins byte-for-byte interop, not just parity
    with our own re-implementation."""
    with mock.patch("core.services.proconnect.time.time", return_value=1700000000):
        timestamp, signature = sign_request(
            SECRET, "GET", f"/api/oidc_providers/{IDP}/configuration", "", None
        )
    assert timestamp == "1700000000"
    assert signature == (
        "84b91f377d8cd445cbfb0879395a75f2ff5a6dfc2799784d37968b83711c0817"
    )

    with mock.patch("core.services.proconnect.time.time", return_value=1700000000):
        _, signature = sign_request(
            SECRET,
            "PATCH",
            f"/api/oidc_providers/{IDP}/configuration",
            "",
            '{"attached_email_domains":["a.fr","b.fr"]}',
        )
    assert signature == (
        "a399e0a8c222713ca9d2adf63711e43e400de8e9c92752912d36e2679a2e83aa"
    )


# --- proxy credential redaction ----------------------------------------------


def test_redact_credentials_strips_userinfo():
    """Proxy userinfo is masked, with and without a password; other text is untouched."""
    assert (
        redact_credentials("socks5://user:s3cr3t@proxy:1080 failed")
        == "socks5://***@proxy:1080 failed"
    )
    # A username-only proxy URL is redacted too (no password present).
    assert (
        redact_credentials("http://bob@proxy:8080 boom") == "http://***@proxy:8080 boom"
    )
    assert redact_credentials("no credentials here") == "no credentials here"


def test_request_error_does_not_leak_proxy_password():
    """A proxy failure must not surface the proxy password in the raised error."""
    client = ProConnectPartnersClient(
        base_url=BASE_URL,
        secret=SECRET,
        proxy_url="socks5://user:s3cr3t@proxy:1080",
    )
    boom = requests.exceptions.ProxyError(
        "Cannot connect to proxy socks5://user:s3cr3t@proxy:1080"
    )
    with mock.patch("core.services.proconnect.requests.request", side_effect=boom):
        with pytest.raises(ProConnectPartnersError) as excinfo:
            client.get_configuration(IDP)
    assert "s3cr3t" not in str(excinfo.value)
    assert "***" in str(excinfo.value)


# --- management command exit codes -------------------------------------------


@proconnect_settings
@responses.activate
def test_sync_command_raises_on_push_failure():
    """A failed push makes the command exit non-zero (CommandError)."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(responses.PATCH, url, json={"error": "boom"}, status=500)
    with pytest.raises(CommandError):
        call_command("proconnect_sync")


def test_sync_command_raises_when_unconfigured():
    """Running the real push while unconfigured is an error, not a silent no-op."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    with override_settings(
        PROCONNECT_API_PARTENAIRES_URL="", PROCONNECT_API_PARTENAIRES_SECRET=""
    ):
        with pytest.raises(CommandError):
            call_command("proconnect_sync")


# --- proconnect_detect_drift -------------------------------------------------


@proconnect_settings
@responses.activate
def test_detect_drift_passes_when_in_sync():
    """No drift when the live provider domains exactly match the intended routing."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.GET,
        url,
        json={"uid": IDP, "attached_email_domains": ["b.fr", "a.fr"]},
        status=200,
    )

    out = StringIO()
    call_command("proconnect_detect_drift", stdout=out)  # no raise
    assert "in sync" in out.getvalue()


@proconnect_settings
@responses.activate
def test_detect_drift_raises_when_lists_differ():
    """Any mismatch between live and intended domains is drift (non-zero exit)."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    # provider is missing b.fr and has an unexpected extra c.fr.
    responses.add(
        responses.GET,
        url,
        json={"uid": IDP, "attached_email_domains": ["a.fr", "c.fr"]},
        status=200,
    )

    with pytest.raises(CommandError):
        call_command("proconnect_detect_drift")


@proconnect_settings
@responses.activate
def test_detect_drift_raises_on_provider_error():
    """A failing configuration read fails the command rather than reporting "clean"."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(responses.GET, url, json={"error": "boom"}, status=500)
    with pytest.raises(CommandError):
        call_command("proconnect_detect_drift")


@proconnect_settings
@responses.activate
def test_detect_drift_ignores_duplicate_live_domains():
    """A duplicated domain in the live config is not drift (compared as a set)."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.GET,
        url,
        json={"uid": IDP, "attached_email_domains": ["a.fr", "a.fr"]},
        status=200,
    )
    out = StringIO()
    call_command("proconnect_detect_drift", stdout=out)  # no raise
    assert "in sync" in out.getvalue()


@proconnect_settings
@responses.activate
def test_detect_drift_idp_id_filter_checks_only_that_provider():
    """--idp-id checks only the given provider (other idps are not GET-ed)."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    _make_proconnect_subscription("other-idp", ["z.fr"])
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.GET,
        url,
        json={"uid": IDP, "attached_email_domains": ["a.fr"]},
        status=200,
    )
    out = StringIO()
    call_command("proconnect_detect_drift", "--idp-id", IDP, stdout=out)
    assert "in sync" in out.getvalue()
    assert len(responses.calls) == 1  # only IDP was checked


@proconnect_settings
def test_detect_drift_no_active_providers():
    """With no active subscription the command calls no API and exits clean."""
    out = StringIO()
    call_command("proconnect_detect_drift", stdout=out)  # no subs → clean no-op
    assert "No active" in out.getvalue()


# --- in-transaction sync: happy path, change-detection, suppression ----------


def _proconnect_api_setup(is_superuser=False):
    """A logged-in operator user managing an org with a proconnect service."""
    user = factories.UserFactory(is_superuser=is_superuser)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],  # makes mail_domain resolvable
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": IDP})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    return client, operator, organization, service


def _subscription_url(operator, organization, service):
    return (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/"
    )


@proconnect_settings
def test_subscription_refuses_a_malformed_domain():
    """A domain the push would drop is refused on write, not stored silently."""
    client, operator, organization, service = _proconnect_api_setup(is_superuser=True)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": False, "metadata": {"domains": ["commune.fr", "pas un domaine"]}},
        format="json",
    )
    assert response.status_code == 400
    assert "pas un domaine" in str(response.json())
    assert not ServiceSubscription.objects.filter(
        service=service, organization=organization
    ).exists()


@proconnect_settings
@responses.activate
def test_subscription_with_a_stored_malformed_domain_stays_editable():
    """A malformed domain stored by an older write must not lock the subscription.

    It is normalized away instead — refusing it here would make the subscription
    impossible to deactivate, which is exactly what one would want to do with it.
    """
    responses.add(
        responses.PATCH,
        f"{BASE_URL}/api/oidc_providers/{IDP}/configuration",
        json={"uid": IDP, "attached_email_domains": []},
        status=200,
    )
    client, operator, organization, service = _proconnect_api_setup(is_superuser=True)
    with suppress_proconnect_sync():
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization,
            service=service,
            operator=operator,
            metadata={"domains": ["commune.fr", "pas un domaine"]},
            is_active=True,
        )

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.is_active is False
    assert subscription.metadata["domains"] == ["commune.fr"]


@proconnect_settings
@responses.activate
def test_activation_surfaces_domain_not_allowed_with_domains():
    """A rejected domain → 400 naming the offending domain, and rolled back."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={
            "error": "attached_email_domain_not_allowed",
            "attached_email_domains": ["commune.fr"],
        },
        status=422,
    )
    client, operator, organization, service = _proconnect_api_setup()

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "commune.fr" in detail
    assert "ProConnect" in detail
    # The activation was rolled back — no subscription persisted.
    assert not ServiceSubscription.objects.filter(
        service=service, organization=organization
    ).exists()


@proconnect_settings
@responses.activate
def test_subscription_activation_pushes_once_on_success():
    """Activating a subscription through the API pushes the provider's domains once."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "attached_email_domains": ["commune.fr"]},
        status=200,
    )
    client, operator, organization, service = _proconnect_api_setup()

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 201
    assert ServiceSubscription.objects.filter(
        service=service, organization=organization
    ).exists()
    assert len(responses.calls) == 1
    assert json.loads(responses.calls[0].request.body) == {
        "attached_email_domains": ["commune.fr"]
    }


@proconnect_settings
@responses.activate
def test_push_fires_across_subscription_lifecycle():
    """A push goes to api-partenaires on: (1) activation, (2) adding/removing a
    domain on an active subscription, and (3) deactivation."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "attached_email_domains": []},
        status=200,
    )
    client, operator, organization, service = _proconnect_api_setup(is_superuser=True)
    endpoint = _subscription_url(operator, organization, service)

    def pushed_domains():
        return json.loads(responses.calls[-1].request.body)["attached_email_domains"]

    # (1) Activate -> pushes the routed mail domain.
    response = client.patch(endpoint, {"is_active": True}, format="json")
    assert response.status_code == 201
    assert len(responses.calls) == 1
    assert pushed_domains() == ["commune.fr"]

    # (2a) Add a domain on the active subscription -> pushes the larger set.
    response = client.patch(
        endpoint, {"metadata": {"domains": ["commune.fr", "extra.fr"]}}, format="json"
    )
    assert response.status_code == 200
    assert len(responses.calls) == 2
    assert pushed_domains() == ["commune.fr", "extra.fr"]

    # (2b) Remove a domain -> pushes the smaller set.
    response = client.patch(
        endpoint, {"metadata": {"domains": ["extra.fr"]}}, format="json"
    )
    assert response.status_code == 200
    assert len(responses.calls) == 3
    assert pushed_domains() == ["extra.fr"]

    # (2c) A save that changes NO domain does not push again (change-detection).
    response = client.patch(
        endpoint, {"metadata": {"domains": ["extra.fr"]}}, format="json"
    )
    assert response.status_code == 200
    assert len(responses.calls) == 3  # unchanged -> no new push

    # (3) Deactivate -> pushes the now-empty set (subscription no longer contributes).
    response = client.patch(endpoint, {"is_active": False}, format="json")
    assert response.status_code == 200
    assert len(responses.calls) == 4
    assert pushed_domains() == []


@proconnect_settings
@responses.activate
def test_subscription_resave_without_domain_change_does_not_repush():
    """A save that changes neither is_active nor the domain set issues no new push."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "attached_email_domains": ["commune.fr"]},
        status=200,
    )
    client, operator, organization, service = _proconnect_api_setup()
    endpoint = _subscription_url(operator, organization, service)

    client.patch(endpoint, {"is_active": True}, format="json")  # create + push
    assert len(responses.calls) == 1

    # Same domains, still active -> no re-push.
    client.patch(endpoint, {"is_active": True}, format="json")
    assert len(responses.calls) == 1

    # Deactivating removes the contribution -> pushes the now-empty set.
    response = client.patch(endpoint, {"is_active": False}, format="json")
    assert response.status_code == 200
    assert len(responses.calls) == 2
    assert json.loads(responses.calls[1].request.body) == {"attached_email_domains": []}


@proconnect_settings
@responses.activate
def test_invalid_entitlement_type_rejected_before_any_push():
    """A bad entitlement type is a 400 at validation time — no push, no drift."""
    client, operator, organization, service = _proconnect_api_setup()
    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "is_active": True,
            "entitlements": [
                {"type": "not_a_real_type", "account_type": "commune", "config": {}}
            ],
        },
        format="json",
    )
    assert response.status_code == 400
    assert len(responses.calls) == 0  # the provider was never contacted
    assert not ServiceSubscription.objects.filter(
        service=service, organization=organization
    ).exists()


@proconnect_settings
@responses.activate
def test_suppress_proconnect_sync_prevents_push():
    """Writes inside suppress_proconnect_sync() do not hit the provider."""
    # No responses mock registered: any HTTP call would raise ConnectionError.
    _make_proconnect_subscription(IDP, ["a.fr"])  # created under suppression
    assert len(responses.calls) == 0


@proconnect_settings
@responses.activate
def test_subscription_delete_pushes_reduced_set():
    """Deleting an active proconnect subscription pushes the now-smaller domain set."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(
        responses.PATCH,
        url,
        json={"uid": IDP, "attached_email_domains": []},
        status=200,
    )
    client, operator, organization, service = _proconnect_api_setup()
    with suppress_proconnect_sync():
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization,
            service=service,
            operator=operator,
            metadata={"domains": ["commune.fr"]},
            is_active=True,
        )

    response = client.delete(_subscription_url(operator, organization, service))
    assert response.status_code == 204
    assert not ServiceSubscription.objects.filter(pk=subscription.pk).exists()
    assert len(responses.calls) == 1
    assert json.loads(responses.calls[0].request.body) == {"attached_email_domains": []}


@proconnect_settings
@responses.activate
def test_subscription_delete_rolls_back_on_push_failure():
    """A failed push on delete rolls back the deletion (subscription survives)."""
    url = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
    responses.add(responses.PATCH, url, json={"error": "boom"}, status=500)
    client, operator, organization, service = _proconnect_api_setup()
    with suppress_proconnect_sync():
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization,
            service=service,
            operator=operator,
            metadata={"domains": ["commune.fr"]},
            is_active=True,
        )

    response = client.delete(_subscription_url(operator, organization, service))
    assert response.status_code == 502
    assert ServiceSubscription.objects.filter(pk=subscription.pk).exists()


@proconnect_settings
@responses.activate
def test_reassigning_the_operator_pushes_both_providers():
    """Moving a subscription between operators re-pushes the old idp and the new one.

    The effective idp_id is resolved per operator, so a subscription whose
    operator changes moves provider with its domain list untouched. Detecting the
    change by domains alone would push neither: the old provider would keep
    advertising the domains, the new one would never receive them.
    """
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    service = subscription.service

    # A second operator on the same service, overriding the idp.
    other_operator = factories.OperatorFactory()
    factories.OperatorServiceConfigFactory(
        operator=other_operator,
        service=service,
        config_override={"idp_id": "other-idp"},
    )
    factories.OperatorOrganizationRoleFactory(
        operator=other_operator, organization=subscription.organization
    )

    for idp in (IDP, "other-idp"):
        responses.add(
            responses.PATCH,
            f"{BASE_URL}/api/oidc_providers/{idp}/configuration",
            json={"uid": idp, "attached_email_domains": []},
            status=200,
        )

    subscription.operator = other_operator
    subscription.save()

    patched = {
        call.request.url.rsplit("/oidc_providers/", 1)[1].split("/")[0]: json.loads(
            call.request.body
        )
        for call in responses.calls
    }
    # The new provider gains the domain, the one it left is recomputed to empty.
    assert patched["other-idp"]["attached_email_domains"] == ["a.fr"]
    assert patched[IDP]["attached_email_domains"] == []


@override_settings(
    PROCONNECT_API_PARTENAIRES_URL="http://api-partenaires-sandbox.test",
    PROCONNECT_API_PARTENAIRES_SECRET=SECRET,
)
def test_client_refuses_a_plaintext_base_url():
    """The HMAC authenticates but does not protect: no signed request over http."""
    client = ProConnectPartnersClient()
    assert client.is_configured is True
    with pytest.raises(ProConnectPartnersError, match="must use https"):
        client.get_configuration(IDP)


@proconnect_settings
@responses.activate
def test_client_does_not_follow_redirects():
    """A 3xx is an error, not a hop: requests would replay X-Signature to the target."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/oidc_providers/{IDP}/configuration",
        status=302,
        headers={"Location": "https://evil.test/steal"},
    )

    client = ProConnectPartnersClient()
    with pytest.raises(ProConnectPartnersError) as excinfo:
        client.get_configuration(IDP)
    assert excinfo.value.status_code == 302
    # Only the original host was contacted; the signature never left for the target.
    assert len(responses.calls) == 1
    assert "evil.test" not in responses.calls[0].request.url
