"""
Tests for the ProConnect api-partenaires domains push (core/proconnect.py).
"""
# pylint: disable=too-many-lines

import hashlib
import hmac
import json
import re
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest
import requests
import responses
from rest_framework.test import APIClient

from core import factories
from core.models import OperatorServiceConfig, ServiceSubscription
from core.services.locks import advisory_lock_key
from core.services.proconnect import (
    BATCH_MAX_RETRY_AFTER,
    DriftReport,
    ProConnectPartnersClient,
    ProConnectPartnersError,
    ProviderDrift,
    check_providers_drift,
    idp_routed_domains,
    redact_credentials,
    sign_request,
    subscription_idp_id,
    sync_proconnect_provider,
    update_out_of_sync,
)
from core.signals import suppress_proconnect_sync

pytestmark = pytest.mark.django_db

BASE_URL = "https://api-partenaires-sandbox.test"
SECRET = "test-oidc-providers-secret"
IDP = "aaa58fc5-0397-495d-8cb5-92b02559d376"
CONFIG_URL = f"{BASE_URL}/api/oidc_providers/{IDP}/configuration"
DOMAINS_URL = f"{BASE_URL}/api/oidc_providers/{IDP}/attached_email_domains"

proconnect_settings = override_settings(
    PROCONNECT_API_PARTENAIRES_URL=BASE_URL,
    PROCONNECT_API_PARTENAIRES_SECRET=SECRET,
)


class FakeProvider:
    """Stand-in for one provider's api-partenaires routes, to register under
    ``@responses.activate``.

    Keeps the attached domains in ``live``, answers the configuration read and the
    per-domain PUT / DELETE like api-partenaires does, and logs each write in
    ``writes`` as ``("PUT" | "DELETE", domain)``. ``refuse`` maps a domain to the
    ``(status, error)`` its PUT is answered with; ``down`` answers every write with
    that status instead, and ``delete_fails`` does so for the DELETE of those
    domains only. ``concurrent`` domains get attached by someone else right after
    each write that goes through.
    """

    def __init__(
        self, idp=IDP, live=(), refuse=None, down=None, delete_fails=(), concurrent=()
    ):
        self.live = set(live)
        self.concurrent = set(concurrent)
        self.refuse = refuse or {}
        self.down = down
        self.delete_fails = set(delete_fails)
        self.writes = []
        base = f"{BASE_URL}/api/oidc_providers/{idp}"
        domain = re.compile(re.escape(f"{base}/attached_email_domains/") + r"[^/]+$")
        responses.add_callback(responses.GET, f"{base}/configuration", self._read)
        responses.add_callback(responses.PUT, domain, self._write)
        responses.add_callback(responses.DELETE, domain, self._write)

    def _read(self, request):
        body = {"uid": IDP, "attached_email_domains": sorted(self.live)}
        return 200, {}, json.dumps(body)

    def _write(self, request):
        domain = request.url.rsplit("/", 1)[1]
        self.writes.append((request.method, domain))
        if self.down:
            return self.down, {}, json.dumps({"error": "down"})
        if request.method == "DELETE":
            if domain in self.delete_fails:
                return 503, {}, json.dumps({"error": "down"})
            if domain not in self.live:
                return 404, {}, json.dumps({"error": "attached_email_domain_not_found"})
            self.live.discard(domain)
            return 204, {}, ""
        if domain in self.refuse:
            status, error = self.refuse[domain]
            return status, {}, json.dumps({"error": error})
        if domain in self.live:
            return 204, {}, ""
        self.live.add(domain)
        self.live |= self.concurrent
        return 201, {}, json.dumps({"domain": domain})


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


def _make_proconnect_subscription(idp_id, domains, is_active=True):
    """Create an active ProConnect subscription resolving to ``idp_id``.

    Suppresses the synchronous push so the factory setup doesn't hit the API.
    """
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": idp_id})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
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
def test_client_attach_email_domain_sends_a_signed_put():
    """One domain per PUT, signed over the path the server sees."""
    responses.add(
        responses.PUT, f"{DOMAINS_URL}/a.fr", json={"domain": "a.fr"}, status=201
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    client.attach_email_domain(IDP, "a.fr")

    request = responses.calls[0].request
    assert request.method == "PUT"
    assert request.body is None
    assert request.headers["X-Signature"] == _expected_signature(
        "PUT",
        f"/api/oidc_providers/{IDP}/attached_email_domains/a.fr",
        request.headers["X-Timestamp"],
    )


@responses.activate
def test_client_attach_email_domain_accepts_an_already_attached_domain():
    """A 204 (already attached) is as good as a 201."""
    responses.add(responses.PUT, f"{DOMAINS_URL}/a.fr", status=204)

    ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET).attach_email_domain(
        IDP, "a.fr"
    )


@responses.activate
def test_client_detach_email_domain_sends_a_signed_delete():
    """A DELETE on the domain's own path, signed like the rest."""
    responses.add(responses.DELETE, f"{DOMAINS_URL}/a.fr", status=204)

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    client.detach_email_domain(IDP, "a.fr")

    request = responses.calls[0].request
    assert request.method == "DELETE"
    assert request.headers["X-Signature"] == _expected_signature(
        "DELETE",
        f"/api/oidc_providers/{IDP}/attached_email_domains/a.fr",
        request.headers["X-Timestamp"],
    )


@responses.activate
def test_client_detach_email_domain_accepts_a_domain_not_attached():
    """A 404 saying the domain was not attached means it is gone: not an error."""
    responses.add(
        responses.DELETE,
        f"{DOMAINS_URL}/a.fr",
        json={"error": "attached_email_domain_not_found"},
        status=404,
    )

    ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET).detach_email_domain(
        IDP, "a.fr"
    )


@responses.activate
def test_client_detach_email_domain_raises_when_the_provider_is_unknown():
    """Any other 404 (here an unknown provider) is a failure."""
    responses.add(
        responses.DELETE,
        f"{DOMAINS_URL}/a.fr",
        json={"error": "not_found"},
        status=404,
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    with pytest.raises(ProConnectPartnersError) as excinfo:
        client.detach_email_domain(IDP, "a.fr")
    assert excinfo.value.status_code == 404


@responses.activate
def test_client_raises_on_error_status():
    """A 4xx/5xx response raises ProConnectPartnersError."""
    responses.add(
        responses.PUT, f"{DOMAINS_URL}/a.fr", json={"error": "boom"}, status=500
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    with pytest.raises(ProConnectPartnersError) as excinfo:
        client.attach_email_domain(IDP, "a.fr")
    assert excinfo.value.domains == []


@responses.activate
@pytest.mark.parametrize(
    "status,error",
    [
        (403, "attached_email_domain_not_allowed"),
        (409, "attached_email_domain_taken"),
        (422, "attached_email_domain_unreachable"),
    ],
)
def test_client_error_names_the_domain_the_provider_refused(status, error):
    """The refusals do not name the domain in the body: the client does."""
    responses.add(
        responses.PUT, f"{DOMAINS_URL}/evil.fr", json={"error": error}, status=status
    )

    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    with pytest.raises(ProConnectPartnersError) as excinfo:
        client.attach_email_domain(IDP, "evil.fr")
    assert excinfo.value.status_code == status
    assert excinfo.value.error_code == error
    assert excinfo.value.domains == ["evil.fr"]


@pytest.mark.parametrize(
    "domain", ["", "A.fr", " a.fr", "a.fr/../b", "a.fr?x=1", "a b.fr", "a", None]
)
def test_client_refuses_a_domain_that_is_not_a_plain_hostname(domain):
    """The domain is interpolated into the signed path: nothing else gets through."""
    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)
    with mock.patch("core.services.proconnect.requests.request") as request:
        with pytest.raises(ProConnectPartnersError, match="Invalid domain"):
            client.attach_email_domain(IDP, domain)
        with pytest.raises(ProConnectPartnersError, match="Invalid domain"):
            client.detach_email_domain(IDP, domain)
    request.assert_not_called()


def _rate_limited(retry_after="3"):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return responses.Response(
        responses.PUT,
        f"{DOMAINS_URL}/a.fr",
        json={"detail": "Too many requests"},
        status=429,
        headers=headers,
    )


def _ok():
    return responses.Response(responses.PUT, f"{DOMAINS_URL}/a.fr", status=204)


@responses.activate
def test_client_retries_a_rate_limited_call_after_retry_after():
    """A 429 is retried once the server's Retry-After has elapsed, signed afresh."""
    responses.add(_rate_limited("3"))
    responses.add(_ok())
    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)

    with mock.patch("core.services.proconnect.time.sleep") as sleep:
        client.attach_email_domain(IDP, "a.fr")

    sleep.assert_called_once_with(3)
    assert len(responses.calls) == 2
    retry = responses.calls[1].request
    assert retry.headers["X-Signature"] == _expected_signature(
        "PUT",
        f"/api/oidc_providers/{IDP}/attached_email_domains/a.fr",
        retry.headers["X-Timestamp"],
    )


@responses.activate
def test_client_gives_up_after_max_retries():
    """A provider that stays rate limited ends in an error, not an endless loop."""
    for _ in range(5):
        responses.add(_rate_limited("1"))
    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)

    with mock.patch("core.services.proconnect.time.sleep") as sleep:
        with pytest.raises(ProConnectPartnersError) as excinfo:
            client.attach_email_domain(IDP, "a.fr")

    assert excinfo.value.status_code == 429
    assert len(responses.calls) == 3  # the call + MAX_RETRIES retries
    assert sleep.call_count == 2


@responses.activate
@pytest.mark.parametrize("retry_after", ["30", "-1", "soon", "", None])
def test_client_does_not_retry_when_retry_after_is_too_long_or_unusable(retry_after):
    """The wait runs inside the caller's transaction: a long or unreadable
    Retry-After fails fast instead of holding it."""
    responses.add(_rate_limited(retry_after))
    client = ProConnectPartnersClient(base_url=BASE_URL, secret=SECRET)

    with mock.patch("core.services.proconnect.time.sleep") as sleep:
        with pytest.raises(ProConnectPartnersError) as excinfo:
            client.attach_email_domain(IDP, "a.fr")

    assert excinfo.value.status_code == 429
    assert len(responses.calls) == 1
    sleep.assert_not_called()


@responses.activate
def test_client_max_retry_after_is_configurable():
    """A batch client may wait out a longer rate-limit window."""
    responses.add(_rate_limited("30"))
    responses.add(_ok())
    client = ProConnectPartnersClient(
        base_url=BASE_URL, secret=SECRET, max_retry_after=BATCH_MAX_RETRY_AFTER
    )

    with mock.patch("core.services.proconnect.time.sleep") as sleep:
        client.attach_email_domain(IDP, "a.fr")

    sleep.assert_called_once_with(30)


def _too_many_requests(method, url):
    responses.add(
        method,
        url,
        json={"detail": "Too many requests"},
        status=429,
        headers={"Retry-After": "30"},
    )


@proconnect_settings
@responses.activate
def test_sync_command_waits_out_a_rate_limit_window():
    """The commands that walk providers accept a Retry-After a web request would not."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    # Read before the push (nothing attached), then by the recheck (a.fr is).
    _drift_get([])
    _drift_get(["a.fr"])
    _too_many_requests(responses.PUT, f"{DOMAINS_URL}/a.fr")
    responses.add(responses.PUT, f"{DOMAINS_URL}/a.fr", status=204)

    with mock.patch("core.services.proconnect.time.sleep") as sleep:
        call_command("proconnect_sync", stdout=StringIO())

    sleep.assert_called_once_with(30)
    assert [c.request.method for c in responses.calls] == ["GET", "PUT", "PUT", "GET"]


@proconnect_settings
@responses.activate
def test_detect_drift_command_waits_out_a_rate_limit_window():
    """Same for the drift check."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    _too_many_requests(responses.GET, CONFIG_URL)
    _drift_get(["a.fr"])

    with mock.patch("core.services.proconnect.time.sleep") as sleep:
        call_command("proconnect_detect_drift", stdout=StringIO())

    sleep.assert_called_once_with(30)
    assert len(responses.calls) == 2


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


def test_idp_routed_domains_ignores_an_operator_idp_override():
    """The idp_id is the service's: an operator override (legacy data) is inert."""
    subscription = _make_proconnect_subscription("base-idp", ["a.fr"])
    # Written around save(), which refuses the key.
    OperatorServiceConfig.objects.filter(service=subscription.service).update(
        config_override={"idp_id": "override-idp"}
    )
    assert subscription_idp_id(subscription) == "base-idp"
    assert idp_routed_domains("base-idp") == ["a.fr"]
    assert idp_routed_domains("override-idp") == []


# --- sync_proconnect_provider ------------------------------------------------


@proconnect_settings
@responses.activate
def test_sync_provider_attaches_the_missing_domains_one_by_one():
    """Each domain the provider lacks gets its own PUT; nothing is sent in bulk."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr"])
    provider = FakeProvider()

    result = sync_proconnect_provider(IDP)

    assert result["success"] is True
    assert result["domains"] == ["a.fr", "b.fr"]
    assert result["attached"] == ["a.fr", "b.fr"]
    assert result["detached"] == []
    assert provider.writes == [("PUT", "a.fr"), ("PUT", "b.fr")]
    assert provider.live == {"a.fr", "b.fr"}
    assert [call.request.method for call in responses.calls] == ["GET", "PUT", "PUT"]


@proconnect_settings
@responses.activate
def test_sync_provider_detaches_what_the_db_no_longer_routes():
    """Detaches come first, so a domain moving between providers is freed in time."""
    _make_proconnect_subscription(IDP, ["b.fr", "c.fr"])
    provider = FakeProvider(live={"a.fr", "b.fr"})

    result = sync_proconnect_provider(IDP)

    assert result["success"] is True
    assert result["attached"] == ["c.fr"]
    assert result["detached"] == ["a.fr"]
    assert provider.writes == [("DELETE", "a.fr"), ("PUT", "c.fr")]
    assert provider.live == {"b.fr", "c.fr"}


@proconnect_settings
@responses.activate
def test_sync_provider_only_reads_a_provider_already_in_sync():
    """No difference, no write: the cost of a push that changes nothing is a GET."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    provider = FakeProvider(live={"a.fr"})

    result = sync_proconnect_provider(IDP)

    assert result["success"] is True
    assert result["attached"] == result["detached"] == []
    assert not provider.writes
    assert len(responses.calls) == 1


@proconnect_settings
@responses.activate
def test_sync_provider_swallows_api_errors():
    """A failing push is reported but never raises."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    FakeProvider(down=500)

    result = sync_proconnect_provider(IDP)
    assert result["success"] is False
    assert "500" in result["error"]


@proconnect_settings
@responses.activate
def test_sync_provider_reports_an_unreadable_provider():
    """Without the live state there is nothing to compare with: no write is tried."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    responses.add(responses.GET, CONFIG_URL, json={"error": "boom"}, status=500)

    result = sync_proconnect_provider(IDP)

    assert result["success"] is False
    assert [call.request.method for call in responses.calls] == ["GET"]


@proconnect_settings
@responses.activate
def test_sync_provider_stops_at_the_first_failure_other_than_a_refusal():
    """A provider that errors is not hammered with the remaining domains."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr", "c.fr"])
    provider = FakeProvider(down=503)

    result = sync_proconnect_provider(IDP)

    assert result["success"] is False
    assert provider.writes == [("PUT", "a.fr")]


@proconnect_settings
@responses.activate
def test_sync_provider_keeps_going_past_a_refused_domain():
    """One domain off the allowlist must not block the others, which stay attached."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr", "c.fr"])
    provider = FakeProvider(refuse={"b.fr": (403, "attached_email_domain_not_allowed")})

    result = sync_proconnect_provider(IDP)

    assert result["success"] is False
    assert "attached_email_domain_not_allowed" in result["error"]
    assert "b.fr" in result["error"]
    assert provider.live == {"a.fr", "c.fr"}


@proconnect_settings
@responses.activate
def test_sync_provider_raises_one_error_naming_every_refused_domain():
    """With raise_on_error the refusals of one kind come as a single error."""
    _make_proconnect_subscription(IDP, ["a.fr", "b.fr", "c.fr"])
    FakeProvider(
        refuse={
            "a.fr": (403, "attached_email_domain_not_allowed"),
            "b.fr": (409, "attached_email_domain_taken"),
            "c.fr": (403, "attached_email_domain_not_allowed"),
        }
    )

    with pytest.raises(ProConnectPartnersError) as excinfo:
        sync_proconnect_provider(IDP, raise_on_error=True)

    # One reason at a time, in the fixed order of DOMAIN_REFUSAL_ERRORS.
    assert excinfo.value.error_code == "attached_email_domain_not_allowed"
    assert excinfo.value.domains == ["a.fr", "c.fr"]


@proconnect_settings
@responses.activate
def test_sync_provider_undoes_its_calls_when_raising():
    """The caller rolls the DB back: the provider must not keep what went through."""
    _make_proconnect_subscription(IDP, ["b.fr", "c.fr"])
    provider = FakeProvider(
        live={"a.fr"}, refuse={"c.fr": (403, "attached_email_domain_not_allowed")}
    )

    with pytest.raises(ProConnectPartnersError):
        sync_proconnect_provider(IDP, raise_on_error=True)

    assert provider.live == {"a.fr"}
    assert provider.writes == [
        ("DELETE", "a.fr"),
        ("PUT", "b.fr"),
        ("PUT", "c.fr"),
        ("DELETE", "b.fr"),
        ("PUT", "a.fr"),
    ]


@proconnect_settings
@responses.activate
def test_sync_provider_keeps_its_calls_when_not_raising():
    """The batch commands make what progress they can and report the rest."""
    _make_proconnect_subscription(IDP, ["b.fr", "c.fr"])
    provider = FakeProvider(
        live={"a.fr"}, refuse={"c.fr": (403, "attached_email_domain_not_allowed")}
    )

    result = sync_proconnect_provider(IDP)

    assert result["success"] is False
    assert provider.live == {"b.fr"}


@proconnect_settings
@responses.activate
def test_sync_provider_undo_stops_at_its_first_failure():
    """A provider that is failing is not asked for the rest of the reversal."""
    _make_proconnect_subscription(IDP, ["b.fr", "c.fr", "d.fr"])
    provider = FakeProvider(
        refuse={"d.fr": (403, "attached_email_domain_not_allowed")},
        delete_fails={"c.fr"},
    )

    with pytest.raises(ProConnectPartnersError):
        sync_proconnect_provider(IDP, raise_on_error=True)

    # c.fr is undone first and fails: b.fr is left for the next push to converge.
    assert provider.writes[-1] == ("DELETE", "c.fr")
    assert ("DELETE", "b.fr") not in provider.writes
    assert provider.live == {"b.fr", "c.fr"}


@proconnect_settings
@responses.activate
def test_sync_provider_takes_a_per_idp_advisory_lock():
    """The read + writes + commit run under a lock keyed on the idp, so two
    concurrent pushes can't each compute a diff and clobber the other's."""
    _make_proconnect_subscription(IDP, ["a.fr"])
    FakeProvider()

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
    provider = FakeProvider()

    out = StringIO()
    call_command("proconnect_sync", stdout=out)
    assert "OK" in out.getvalue()
    assert IDP in out.getvalue()
    assert provider.live == {"a.fr"}


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
    FakeProvider(down=500)

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
    FakeProvider(down=500)
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


# --- Service.out_of_sync (config["out_of_sync"]) ------------------------------


def _flag_out_of_sync(service):
    service.config = {**(service.config or {}), "out_of_sync": True}
    service.save()


def _drift_get(live_domains, status=200):
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/oidc_providers/{IDP}/configuration",
        json={"uid": IDP, "attached_email_domains": live_domains},
        status=status,
    )


@proconnect_settings
@responses.activate
def test_detect_drift_flags_the_service_out_of_sync():
    """A drifted provider flags its services; other providers' services stay clean."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _drift_get(["a.fr", "c.fr"])

    with pytest.raises(CommandError):
        call_command("proconnect_detect_drift")

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True
    # Stored next to the rest of the service config, which it leaves alone.
    assert subscription.service.config == {"idp_id": IDP, "out_of_sync": True}


@proconnect_settings
@responses.activate
def test_detect_drift_clears_the_flag_once_in_sync():
    """The next run clears the flag when the provider matches again."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)
    _drift_get(["a.fr"])

    call_command("proconnect_detect_drift")

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False
    assert subscription.service.config == {"idp_id": IDP}


@proconnect_settings
@responses.activate
def test_detect_drift_keeps_the_flag_when_the_provider_is_unreadable():
    """No reading is no evidence: the flag is neither set nor cleared."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)
    _drift_get([], status=500)

    with pytest.raises(CommandError):
        call_command("proconnect_detect_drift")

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True


@proconnect_settings
@responses.activate
def test_detect_drift_rechecks_a_flagged_provider_without_active_subscription():
    """Otherwise nothing could ever clear the flag of a provider left unused."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"], is_active=False)
    _flag_out_of_sync(subscription.service)
    _drift_get([])

    call_command("proconnect_detect_drift")

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False


@proconnect_settings
@responses.activate
def test_detect_drift_does_not_flag_what_a_locked_recheck_finds_in_sync():
    """A first read can predate a commit: the recheck under the lock decides."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _drift_get(["a.fr"])
    stale = {IDP: ["stale.fr"]}

    report = check_providers_drift({IDP}, ProConnectPartnersClient(), routed=stale)
    update_out_of_sync(report)

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False
    assert IDP in report.in_sync


def test_update_out_of_sync_judges_a_service_by_the_provider_it_has_now():
    """A service moved to another provider is not flagged for the one it left."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    service = subscription.service
    report = DriftReport(
        drifted={"left-provider": ProviderDrift(missing=["x.fr"], unexpected=[])},
        in_sync={IDP: 1},
        unreadable={},
    )
    # The mapping an earlier read would have given, before the move.
    with mock.patch(
        "core.services.proconnect.service_idp_ids",
        return_value={service.pk: "left-provider"},
    ):
        update_out_of_sync(report)

    service.refresh_from_db()
    assert service.out_of_sync is False


def test_update_out_of_sync_leaves_a_service_the_report_does_not_cover():
    """Neither drifted nor in sync (unreadable, not checked): nothing changes."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)

    update_out_of_sync(DriftReport(drifted={}, in_sync={}, unreadable={}))

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True


@proconnect_settings
def test_out_of_sync_service_blocks_subscription_writes():
    """PATCH and DELETE are refused with a 409 and change nothing."""
    client, operator, organization, service = _proconnect_api_setup(is_superuser=True)
    with suppress_proconnect_sync():
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization,
            service=service,
            operator=operator,
            metadata={"domains": ["commune.fr"]},
            is_active=True,
        )
    _flag_out_of_sync(service)
    url = _subscription_url(operator, organization, service)

    patched = client.patch(url, {"is_active": False}, format="json")
    deleted = client.delete(url)

    assert patched.status_code == 409
    assert deleted.status_code == 409
    assert "synchronisé" in patched.json()["detail"]
    subscription.refresh_from_db()
    assert subscription.is_active is True


@proconnect_settings
def test_out_of_sync_service_is_exposed_to_the_frontend():
    """The organization's service payload carries the flag."""
    client, operator, organization, service = _proconnect_api_setup()
    _flag_out_of_sync(service)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/"
    )

    assert response.status_code == 200
    assert response.json()["out_of_sync"] is True


@proconnect_settings
@responses.activate
def test_sync_command_clears_the_flag_after_the_push():
    """The repair command does not leave the services blocked until the next cron."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)
    FakeProvider()

    call_command("proconnect_sync", stdout=StringIO())

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False


@proconnect_settings
@responses.activate
def test_sync_command_flags_the_service_when_the_push_failed():
    """A failed push leaves the provider drifted: the API must stop writing now."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    FakeProvider(down=500)

    with pytest.raises(CommandError):
        call_command("proconnect_sync", stdout=StringIO(), stderr=StringIO())

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True


@proconnect_settings
@responses.activate
def test_sync_command_dry_run_does_not_recheck():
    """Nothing was pushed, so there is nothing to recheck."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)

    call_command("proconnect_sync", "--dry-run", stdout=StringIO())

    assert len(responses.calls) == 0
    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True


@proconnect_settings
@responses.activate
def test_subscribe_bulk_clears_the_flag_after_the_push():
    """The bulk push fixes the provider, so the flag goes with it."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)
    FakeProvider(live={"a.fr"})

    call_command(
        "subscribe_bulk",
        "unsubscribe",
        "--service",
        str(subscription.service_id),
        "--soft",
        stdout=StringIO(),
    )

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False


@proconnect_settings
@responses.activate
def test_subscribe_bulk_flags_the_service_when_the_push_failed():
    """Rows written but provider not updated: flagged without waiting for the cron."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    FakeProvider(live={"a.fr"}, down=500)

    with pytest.raises(CommandError):
        call_command(
            "subscribe_bulk",
            "unsubscribe",
            "--service",
            str(subscription.service_id),
            "--soft",
            stdout=StringIO(),
            stderr=StringIO(),
        )

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True


@proconnect_settings
@responses.activate
def test_saving_a_subscription_clears_the_flag_once_committed(
    django_capture_on_commit_callbacks,
):
    """A push that fixes a flagged provider is rechecked after the commit."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    _flag_out_of_sync(subscription.service)
    FakeProvider(live={"a.fr"})

    subscription.is_active = False
    with django_capture_on_commit_callbacks(execute=True):
        subscription.save()

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False


@proconnect_settings
@responses.activate
def test_saving_a_subscription_does_not_recheck_an_unflagged_provider(
    django_capture_on_commit_callbacks,
):
    """The recheck is one more request: only paid when the provider is flagged."""
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    FakeProvider(live={"a.fr"})

    subscription.is_active = False
    with django_capture_on_commit_callbacks(execute=True):
        subscription.save()

    # The push (a read, then the detach) and no second read.
    assert [call.request.method for call in responses.calls] == ["GET", "DELETE"]


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
def test_subscription_refuses_a_domain_api_partenaires_would_refuse_as_too_long():
    """A label over 63 characters is a 400 now, not a failed push later."""
    client, operator, organization, service = _proconnect_api_setup(is_superuser=True)
    too_long = f"{'a' * 64}.fr"

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": False, "metadata": {"domains": [too_long]}},
        format="json",
    )

    assert response.status_code == 400
    assert too_long in str(response.json())


@proconnect_settings
@responses.activate
def test_subscription_with_a_stored_malformed_domain_stays_editable():
    """A malformed domain stored by an older write must not lock the subscription.

    It is normalized away instead — refusing it here would make the subscription
    impossible to deactivate, which is exactly what one would want to do with it.
    """
    FakeProvider(live={"commune.fr"})
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
    FakeProvider(refuse={"commune.fr": (403, "attached_email_domain_not_allowed")})
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
@pytest.mark.parametrize(
    "error,status,expected",
    [
        ("attached_email_domain_unreachable", 422, "MX"),
        ("attached_email_domain_taken", 409, "autre fournisseur"),
    ],
)
def test_activation_surfaces_unreachable_and_taken_domains(error, status, expected):
    """Each rejection that names domains gets its own 400 message, and rolls back."""
    FakeProvider(refuse={"commune.fr": (status, error)})
    client, operator, organization, service = _proconnect_api_setup()

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": True},
        format="json",
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "commune.fr" in detail
    assert expected in detail
    assert "pas encore autorisés" not in detail
    assert not ServiceSubscription.objects.filter(
        service=service, organization=organization
    ).exists()


@proconnect_settings
@responses.activate
def test_activation_keeps_the_generic_502_for_other_push_errors():
    """Errors that name no domain (here a DNS outage upstream) stay a generic 502."""
    FakeProvider(refuse={"commune.fr": (502, "dns_unavailable")})
    client, operator, organization, service = _proconnect_api_setup()

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": True},
        format="json",
    )

    assert response.status_code == 502


@proconnect_settings
@responses.activate
def test_subscription_activation_pushes_once_on_success():
    """Activating a subscription through the API pushes the provider's domains once."""
    provider = FakeProvider()
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
    assert provider.writes == [("PUT", "commune.fr")]
    assert len(responses.calls) == 2  # the read, then the one domain


@proconnect_settings
@responses.activate
def test_push_fires_across_subscription_lifecycle():
    """The provider follows: (1) activation, (2) adding/removing a domain on an
    active subscription, and (3) deactivation, one domain per call."""
    provider = FakeProvider()
    client, operator, organization, service = _proconnect_api_setup(is_superuser=True)
    endpoint = _subscription_url(operator, organization, service)

    def writes_since_last():
        writes, provider.writes = provider.writes, []
        return writes

    # (1) Activate -> attaches the routed mail domain.
    response = client.patch(endpoint, {"is_active": True}, format="json")
    assert response.status_code == 201
    assert writes_since_last() == [("PUT", "commune.fr")]

    # (2a) Add a domain on the active subscription -> attaches only that one.
    response = client.patch(
        endpoint, {"metadata": {"domains": ["commune.fr", "extra.fr"]}}, format="json"
    )
    assert response.status_code == 200
    assert writes_since_last() == [("PUT", "extra.fr")]
    assert provider.live == {"commune.fr", "extra.fr"}

    # (2b) Remove a domain -> detaches only that one.
    response = client.patch(
        endpoint, {"metadata": {"domains": ["extra.fr"]}}, format="json"
    )
    assert response.status_code == 200
    assert writes_since_last() == [("DELETE", "commune.fr")]
    assert provider.live == {"extra.fr"}

    # (2c) A save that changes NO domain does not reach the provider at all
    # (change-detection).
    calls = len(responses.calls)
    response = client.patch(
        endpoint, {"metadata": {"domains": ["extra.fr"]}}, format="json"
    )
    assert response.status_code == 200
    assert len(responses.calls) == calls

    # (3) Deactivate -> detaches the rest (subscription no longer contributes).
    response = client.patch(endpoint, {"is_active": False}, format="json")
    assert response.status_code == 200
    assert writes_since_last() == [("DELETE", "extra.fr")]
    assert provider.live == set()


@proconnect_settings
@responses.activate
def test_subscription_resave_without_domain_change_does_not_repush():
    """A save that changes neither is_active nor the domain set issues no new push."""
    provider = FakeProvider()
    client, operator, organization, service = _proconnect_api_setup()
    endpoint = _subscription_url(operator, organization, service)

    client.patch(endpoint, {"is_active": True}, format="json")  # create + push
    assert len(responses.calls) == 2

    # Same domains, still active -> no re-push.
    client.patch(endpoint, {"is_active": True}, format="json")
    assert len(responses.calls) == 2

    # Deactivating removes the contribution -> detaches the domain.
    response = client.patch(endpoint, {"is_active": False}, format="json")
    assert response.status_code == 200
    assert provider.writes == [("PUT", "commune.fr"), ("DELETE", "commune.fr")]


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
    """Deleting an active proconnect subscription detaches its domains."""
    provider = FakeProvider(live={"commune.fr"})
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
    assert provider.writes == [("DELETE", "commune.fr")]


@proconnect_settings
@responses.activate
def test_subscription_delete_rolls_back_on_push_failure():
    """A failed push on delete rolls back the deletion (subscription survives)."""
    FakeProvider(live={"commune.fr"}, down=500)
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
def test_subscription_create_inactive_does_not_push():
    """Creating an inactive subscription changes no pushed set: no push, so an
    unreachable provider does not block it."""
    FakeProvider(down=503)
    client, operator, organization, service = _proconnect_api_setup()

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"is_active": False},
        format="json",
    )

    assert response.status_code == 201
    assert ServiceSubscription.objects.filter(
        service=service, organization=organization, is_active=False
    ).exists()
    assert len(responses.calls) == 0


@proconnect_settings
@responses.activate
def test_subscription_delete_inactive_does_not_push():
    """Deleting an inactive subscription removes nothing from the pushed set."""
    FakeProvider(down=503)
    client, operator, organization, service = _proconnect_api_setup()
    with suppress_proconnect_sync():
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization,
            service=service,
            operator=operator,
            metadata={"domains": ["commune.fr"]},
            is_active=False,
        )

    response = client.delete(_subscription_url(operator, organization, service))

    assert response.status_code == 204
    assert not ServiceSubscription.objects.filter(pk=subscription.pk).exists()
    assert len(responses.calls) == 0


@proconnect_settings
@responses.activate
def test_admin_add_inactive_subscription_does_not_push():
    """The admin add form creates an inactive subscription without a push."""
    FakeProvider(down=503)
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": IDP})

    response = _admin_client().post(
        reverse("admin:core_servicesubscription_add"),
        {
            "organization": str(organization.pk),
            "operator": str(operator.pk),
            "service": str(service.pk),
            "metadata": json.dumps({"domains": ["commune.fr"]}),
        },
    )

    assert response.status_code == 302
    assert ServiceSubscription.objects.filter(
        service=service, organization=organization, is_active=False
    ).exists()
    assert len(responses.calls) == 0


@proconnect_settings
@responses.activate
def test_reassigning_the_service_pushes_both_providers():
    """Moving a subscription to another service re-pushes the old idp and the new one.

    The idp_id comes from the service, so a subscription whose service changes
    moves provider with its domain list untouched. Detecting the change by domains
    alone would push neither: the old provider would keep advertising the domains,
    the new one would never receive them.
    """
    subscription = _make_proconnect_subscription(IDP, ["a.fr"])
    other_service = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "other-idp"}
    )

    old_provider = FakeProvider(live={"a.fr"})
    new_provider = FakeProvider(idp="other-idp")

    subscription.service = other_service
    subscription.save()

    # The new provider gains the domain, the one it left loses it.
    assert new_provider.live == {"a.fr"}
    assert old_provider.live == set()


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


# --- django admin: subscription change form and ProConnect domains page -----


def _admin_client():
    """A logged-in staff superuser for the django admin."""
    user = factories.UserFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    return client


def _admin_change_post(subscription, **overrides):
    """The change form payload for a subscription, with is_active checked."""
    data = {
        "organization": str(subscription.organization_id),
        "operator": str(subscription.operator_id),
        "service": str(subscription.service_id),
        "is_active": "on",
        "metadata": json.dumps({"domains": ["autre.fr"]}),
        "_continue": "Save and continue editing",
    }
    data.update(overrides)
    return data


@proconnect_settings
@responses.activate
def test_admin_change_form_always_pushes():
    """The regular change form has no skip option: a posted one is ignored."""
    provider = FakeProvider(live={"commune.fr"})
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])
    url = reverse("admin:core_servicesubscription_change", args=[subscription.pk])

    response = _admin_client().post(
        url, _admin_change_post(subscription, skip_proconnect_sync="on")
    )

    assert response.status_code == 302
    subscription.refresh_from_db()
    assert subscription.metadata["domains"] == ["autre.fr"]
    assert provider.writes == [("DELETE", "commune.fr"), ("PUT", "autre.fr")]


def _manual_actions_url(subscription):
    return reverse(
        "admin:core_servicesubscription_proconnect_manual_actions",
        args=[subscription.pk],
    )


def test_admin_change_form_links_proconnect_manual_actions():
    """A ProConnect subscription's change form links to the manual actions page."""
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])
    url = reverse("admin:core_servicesubscription_change", args=[subscription.pk])

    response = _admin_client().get(url)

    assert response.status_code == 200
    assert _manual_actions_url(subscription) in response.content.decode()


def test_admin_proconnect_manual_actions_page_shows_state():
    """The page shows the current domains and active state."""
    subscription = _make_proconnect_subscription(IDP, ["commune.fr", "mairie.fr"])

    response = _admin_client().get(_manual_actions_url(subscription))

    assert response.status_code == 200
    content = response.content.decode()
    assert "commune.fr" in content
    assert "mairie.fr" in content
    assert 'name="is_active" id="id_is_active" checked' in content


def test_admin_proconnect_manual_actions_not_for_other_services():
    """The page 404s for a non-ProConnect subscription."""
    subscription = factories.ServiceSubscriptionFactory(
        service=factories.ServiceFactory(type="adc"),
        operator=factories.OperatorFactory(),
    )

    response = _admin_client().get(_manual_actions_url(subscription))

    assert response.status_code == 404


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_add_pushes():
    """Adding a domain saves it and attaches it to the provider."""
    provider = FakeProvider(live={"commune.fr"})
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])

    response = _admin_client().post(
        _manual_actions_url(subscription),
        {"domain": " Autre.FR ", "add": "", "is_active": "on"},
    )

    assert response.status_code == 302
    subscription.refresh_from_db()
    assert subscription.metadata["domains"] == ["autre.fr", "commune.fr"]
    assert provider.writes == [("PUT", "autre.fr")]


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_skip_push():
    """With the skip box, the change is saved without contacting the provider."""
    # No responses mock registered: any HTTP call would raise ConnectionError.
    subscription = _make_proconnect_subscription(IDP, ["commune.fr", "mairie.fr"])

    response = _admin_client().post(
        _manual_actions_url(subscription),
        {"remove": "commune.fr", "is_active": "on", "skip_proconnect_sync": "on"},
    )

    assert response.status_code == 302
    subscription.refresh_from_db()
    assert subscription.metadata["domains"] == ["mairie.fr"]
    assert len(responses.calls) == 0


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_activate_without_push():
    """With the skip box, activating works while the provider is down."""
    FakeProvider(down=503)
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"], is_active=False)

    response = _admin_client().post(
        _manual_actions_url(subscription),
        {"save": "", "is_active": "on", "skip_proconnect_sync": "on"},
    )

    assert response.status_code == 302
    subscription.refresh_from_db()
    assert subscription.is_active is True
    assert len(responses.calls) == 0


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_deactivate_pushes():
    """Deactivating without the skip box detaches the domains."""
    provider = FakeProvider(live={"commune.fr"})
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])

    response = _admin_client().post(_manual_actions_url(subscription), {"save": ""})

    assert response.status_code == 302
    subscription.refresh_from_db()
    assert subscription.is_active is False
    assert provider.writes == [("DELETE", "commune.fr")]


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_save_pushes_unchanged_state():
    """A plain save pushes even though nothing changed: that is how drift is fixed."""
    provider = FakeProvider(live={"stray.fr"})
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])

    response = _admin_client().post(
        _manual_actions_url(subscription), {"save": "", "is_active": "on"}
    )

    assert response.status_code == 302
    assert provider.writes == [("DELETE", "stray.fr"), ("PUT", "commune.fr")]
    assert provider.live == {"commune.fr"}


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_save_clears_out_of_sync():
    """Fixing the provider from the form lifts the API block."""
    FakeProvider()
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])
    _flag_out_of_sync(subscription.service)
    client = _admin_client()
    assert (
        "out of sync" in client.get(_manual_actions_url(subscription)).content.decode()
    )

    client.post(_manual_actions_url(subscription), {"save": "", "is_active": "on"})

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is False


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_still_drifted_keeps_the_flag():
    """If the provider still differs after the save, the block stays and says so."""
    # Something else attaches a domain while the form is being saved.
    FakeProvider(concurrent={"autre.fr"})
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])
    _flag_out_of_sync(subscription.service)

    response = _admin_client().post(
        _manual_actions_url(subscription),
        {"save": "", "is_active": "on"},
        follow=True,
    )

    subscription.service.refresh_from_db()
    assert subscription.service.out_of_sync is True
    assert "still out of sync" in response.content.decode()


@proconnect_settings
@responses.activate
def test_admin_proconnect_manual_actions_failed_push_rolls_back():
    """A failed push leaves the subscription unchanged and reports the error."""
    FakeProvider(down=500)
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])

    response = _admin_client().post(
        _manual_actions_url(subscription),
        {"domain": "autre.fr", "add": "", "is_active": "on"},
    )

    assert response.status_code == 200
    assert "The ProConnect push failed" in response.content.decode()
    subscription.refresh_from_db()
    assert subscription.metadata["domains"] == ["commune.fr"]


@pytest.mark.parametrize(
    "post, error",
    [
        ({"domain": "not a domain", "add": ""}, "Not valid domain name"),
        ({"domain": "", "add": ""}, "Enter a domain to add."),
        ({"remove": "commune.fr"}, "Mail domain is required"),
        ({"domain": "pris.fr", "add": ""}, "already used by another active"),
    ],
)
def test_admin_proconnect_manual_actions_refused(post, error):
    """The API's domain rules apply: nothing is saved and the reason is shown."""
    _make_proconnect_subscription(IDP, ["pris.fr"])
    subscription = _make_proconnect_subscription(IDP, ["commune.fr"])

    response = _admin_client().post(
        _manual_actions_url(subscription),
        {**post, "is_active": "on", "skip_proconnect_sync": "on"},
    )

    assert response.status_code == 200
    assert error in response.content.decode()
    subscription.refresh_from_db()
    assert subscription.metadata["domains"] == ["commune.fr"]
    assert subscription.is_active is True
