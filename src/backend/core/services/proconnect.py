"""
Client and helpers for the ProConnect "api-partenaires" API.

Pushes the full list of authorized email domains for a given OIDC provider
(identified by its ``idp_id`` / provider uid) to
https://github.com/proconnect-gouv/api-partenaires

api-partenaires calls those domains ``attached_email_domains``; everywhere on this
side they are just "domains".

Authentication is a shared HMAC-SHA256 secret that is *global* to all
``/api/oidc_providers/*`` routes (per-provider access is enforced by the
api-partenaires allowlist on their side, not by the secret). The signed
message is::

    {timestamp}:{METHOD}:{path}?{query}[:{body}]

and is sent in the ``X-Timestamp`` / ``X-Signature`` headers. The body, when
present, must be signed byte-for-byte as it is sent on the wire.
"""
# pylint: disable=too-many-lines

import hashlib
import hmac
import json
import logging
import re
import time
from collections import defaultdict
from typing import NamedTuple, Optional
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models import Q

import requests
import sentry_sdk

from core.models import (
    Operator,
    OperatorServiceConfig,
    Organization,
    Service,
    ServiceSubscription,
)
from core.services.domainnames import normalize_domains
from core.services.locks import lock_idp

logger = logging.getLogger(__name__)

# (connect, read). Deliberately short: the push runs inside the request's
# transaction, so this bounds how long a DB connection (and the row locks taken
# by the subscription validation) is held hostage by a slow api-partenaires.
# A timeout surfaces as a 502 and the user retries.
DEFAULT_TIMEOUT = (3, 5)

# api-partenaires rate limits its signed routes (429 + Retry-After). A 429 is
# retried when the server asks for a wait of at most ``max_retry_after`` seconds,
# at most ``MAX_RETRIES`` times. The wait happens inside the request's transaction
# like the call itself, so the default is short; batch commands that walk many
# providers may afford a whole 60s rate-limit window.
MAX_RETRIES = 2
DEFAULT_MAX_RETRY_AFTER = 10
BATCH_MAX_RETRY_AFTER = 65

# Payload key and error codes carrying the provider's domain list.
ATTACHED_EMAIL_DOMAINS_KEY = "attached_email_domains"
DOMAIN_NOT_ALLOWED_ERROR = "attached_email_domain_not_allowed"
DOMAIN_UNREACHABLE_ERROR = "attached_email_domain_unreachable"
DOMAIN_TAKEN_ERROR = "attached_email_domain_taken"

# Key of the per-provider domain list in the oidc_providers allowlist YAML (the
# file that gates api-partenaires).
ALLOWED_DOMAINS_KEY = "allowed_attached_email_domains"

# Matches URL userinfo (``scheme://user[:pass]@host``) for redaction.
_CREDENTIALS_RE = re.compile(r"://[^/\s:@]+(?::[^/\s@]+)?@")

# Provider uid charset. The uid is operator-supplied config that we interpolate
# into the api-partenaires request path *and* the signed message, so it must not
# be able to introduce a path segment (``..``, ``/``) or a query/fragment.
_IDP_ID_RE = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")


def redact_credentials(text: str) -> str:
    """Strip ``user[:pass]@`` credentials from any URL in a string (e.g. proxy URLs).

    Underlying ``requests``/PySocks exceptions can embed the full proxy URL —
    including its password — in their message; scrub it before logging. Also used
    on operator-supplied URLs (``--url`` flags) before they reach an error message.
    """
    return _CREDENTIALS_RE.sub("://***@", text)


class ProConnectPartnersError(Exception):
    """Raised when a call to the api-partenaires API fails.

    Carries the structured details of the api-partenaires error response when
    available (``error_code``/``domains``), so callers can surface an actionable
    message — notably ``attached_email_domain_not_allowed`` with the offending
    domains.
    """

    def __init__(self, message, status_code=None, error_code=None, domains=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.domains = domains or []


def validate_idp_id(idp_id: str) -> str:
    """Return ``idp_id`` if it is safe to interpolate into a request path.

    Raises :class:`ProConnectPartnersError` otherwise — a malformed uid must never
    reach the wire, since the same string is both signed and routed.
    """
    if not isinstance(idp_id, str) or not _IDP_ID_RE.fullmatch(idp_id):
        raise ProConnectPartnersError(f"Invalid ProConnect idp_id: {idp_id!r}")
    return idp_id


def sign_request(
    secret: str, method: str, path: str, query: str, body: Optional[str]
) -> tuple[str, str]:
    """Return an ``(timestamp, signature)`` pair for the given request.

    The message format mirrors the api-partenaires signature middleware:
    ``{timestamp}:{METHOD}:{path}?{query}`` optionally followed by
    ``:{body}`` when a body is present.
    """
    timestamp = str(int(time.time()))
    message = f"{timestamp}:{method}:{path}?{query}"
    if body:
        message += f":{body}"
    signature = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return timestamp, signature


class ProConnectPartnersClient:
    """Minimal signed client for the api-partenaires OIDC providers API."""

    def __init__(
        self,
        base_url=None,
        secret=None,
        timeout=DEFAULT_TIMEOUT,
        proxy_url=None,
        max_retry_after=DEFAULT_MAX_RETRY_AFTER,
    ):
        base_url = (
            base_url
            if base_url is not None
            else (settings.PROCONNECT_API_PARTENAIRES_URL or "")
        )
        self.base_url = base_url.rstrip("/")
        self.secret = (
            secret if secret is not None else settings.PROCONNECT_API_PARTENAIRES_SECRET
        )
        # Optional SOCKS5 proxy (e.g. "socks5://user:pass@host:1080"); requires
        # the PySocks-backed "socks" extra of requests.
        self.proxy_url = (
            proxy_url
            if proxy_url is not None
            else settings.PROCONNECT_API_PARTENAIRES_PROXY_URL
        )
        self.timeout = timeout
        self.max_retry_after = max_retry_after

    @property
    def is_configured(self) -> bool:
        """Whether both a base URL and a secret are available."""
        return bool(self.base_url and self.secret)

    def _send(self, method, path, url, signed_path, body):
        """One signed HTTP call. Signed afresh each time: the timestamp expires."""
        timestamp, signature = sign_request(self.secret, method, signed_path, "", body)
        headers = {
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        proxies = (
            {"http": self.proxy_url, "https": self.proxy_url}
            if self.proxy_url
            else None
        )
        try:
            return requests.request(
                method,
                url,
                headers=headers,
                # Send the exact bytes that were signed: a str body would be
                # encoded latin-1 by http.client, while the signature is over
                # its utf-8 encoding.
                data=body.encode("utf-8") if body is not None else None,
                timeout=self.timeout,
                proxies=proxies,
                # X-Signature is a custom header, so requests would replay it to
                # the redirect target (it only strips Authorization). A 3xx must
                # not be able to walk our signature to another host — and the
                # signature covers the original path anyway, so following one
                # could never authenticate. Treated as an error by the caller.
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as e:
            raise ProConnectPartnersError(
                redact_credentials(f"{method} {path} failed: {e}")
            ) from e

    def _retry_wait(self, response) -> Optional[int]:
        """Seconds to wait before retrying a 429, or ``None`` to give up.

        Gives up when the server's ``Retry-After`` is missing, not a number of
        seconds, or longer than ``max_retry_after``.
        """
        if response.status_code != 429:
            return None
        try:
            wait = int(response.headers.get("Retry-After", ""))
        except ValueError:
            return None
        return wait if 0 <= wait <= self.max_retry_after else None

    def _request(self, method: str, path: str, body: Optional[str] = None) -> dict:
        if not self.is_configured:
            raise ProConnectPartnersError(
                "api-partenaires client is not configured "
                "(PROCONNECT_API_PARTENAIRES_URL / PROCONNECT_API_PARTENAIRES_SECRET)."
            )

        # The HMAC authenticates the request; it does not protect it. Over
        # plaintext the whole signed request — and a signature an eavesdropper can
        # replay within the timestamp window — is on the wire. A mistyped scheme
        # must fail loudly here rather than silently downgrade every push.
        scheme = urlsplit(self.base_url).scheme
        if scheme != "https":
            raise ProConnectPartnersError(
                f"PROCONNECT_API_PARTENAIRES_URL must use https, got {scheme or 'none'}."
            )

        # Sign the path the server will actually see: when the base URL carries a
        # prefix, urljoin puts it in front of ``path``, and signing the bare
        # ``path`` would not match the middleware's own computation.
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        signed_path = urlsplit(url).path

        response = self._send(method, path, url, signed_path, body)
        for _ in range(MAX_RETRIES):
            wait = self._retry_wait(response)
            if wait is None:
                break
            logger.warning(
                "api-partenaires rate limited %s %s, retrying in %ss",
                method,
                path,
                wait,
            )
            time.sleep(wait)
            response = self._send(method, path, url, signed_path, body)

        # Anything that is not a 2xx, redirects included: with allow_redirects
        # off, a 3xx reaches here and `>= 400` would let it fall through to
        # response.json() as if it were a result.
        if not 200 <= response.status_code < 300:
            error_code = None
            domains = None
            try:
                data = response.json()
            except ValueError:
                data = None
            if isinstance(data, dict):
                error_code = data.get("error")
                domains = data.get(ATTACHED_EMAIL_DOMAINS_KEY)
            raise ProConnectPartnersError(
                f"{method} {path} failed with status {response.status_code}: "
                f"{response.text[:500]}",
                status_code=response.status_code,
                error_code=error_code,
                domains=domains if isinstance(domains, list) else None,
            )

        try:
            return response.json()
        except ValueError:
            return {}

    def get_configuration(self, idp_id: str) -> dict:
        """Read the current provider configuration (uid, name, domains, ...)."""
        path = f"/api/oidc_providers/{validate_idp_id(idp_id)}/configuration"
        return self._request("GET", path)

    def set_attached_email_domains(self, idp_id: str, domains: list[str]) -> dict:
        """Replace the provider's attached email domains with the given list."""
        path = f"/api/oidc_providers/{validate_idp_id(idp_id)}/configuration"
        # Serialize once and sign/send the exact same bytes.
        body = json.dumps({ATTACHED_EMAIL_DOMAINS_KEY: domains}, separators=(",", ":"))
        return self._request("PATCH", path, body=body)


# ---------------------------------------------------------------------------
# Per-organization ProConnect domain state.
#
# The Organization model only stores the raw ``proconnect_domains`` JSON dict;
# every read/derivation lives here as a simple ``fn(organization)`` API.
#
# The five buckets are not five of a kind. They answer two questions:
#
#   provenance — where the domain came from:
#       "dpnt"        declared on service-public.gouv.fr (DILA), authoritative
#       "candidates"  generated from the collectivité's name, a guess
#       "manual"      added by a superuser
#   statut — how far it got:
#       "requested"   asked for by an operator member, awaiting validation
#       "discarded"   set aside by a superuser (a tombstone, not a provenance)
#
# Two derived sets are all the rest of the code needs, and both live here so the
# rule is written once:
#
#   known_domains(org)      every domain we display for the org
#   routable_domains(org)   the subset it may actually route to a provider
# ---------------------------------------------------------------------------

# Buckets stored in ``Organization.proconnect_domains``.
PROCONNECT_DOMAIN_BUCKETS = (
    "requested",
    "manual",
    "dpnt",
    "candidates",
    "discarded",
)

# Provenances feeding the routable set, low → high priority. A domain carrying
# several keeps the highest one (what the allowlist YAML comments report).
# "routed" is not a bucket: it is what the org's active subscriptions send today.
ROUTABLE_PROVENANCES = ("routed", "candidates", "manual", "dpnt")

# Source of each allowed domain in the file api-partenaires reads:
#   "routed"     already live: an active subscription sends it today
#   "dila"       not live, declared on service-public.gouv.fr (``dpnt``); needs a
#                valid fiche
#   "manual"     not live, added by a superuser (``manual``)
#   "candidate"  everything else (``candidates``)
# The best applicable wins, in that order.
ALLOWLIST_SOURCE_DILA = "dila"
ALLOWLIST_SOURCE_ROUTED = "routed"
ALLOWLIST_SOURCE_MANUAL = "manual"
ALLOWLIST_SOURCE_CANDIDATE = "candidate"
ALLOWLIST_SOURCES = (
    ALLOWLIST_SOURCE_DILA,
    ALLOWLIST_SOURCE_ROUTED,
    ALLOWLIST_SOURCE_MANUAL,
    ALLOWLIST_SOURCE_CANDIDATE,
)

# Organization types that have a Service-Public fiche: a row of one of these
# carries it whatever its source.
FICHE_ORG_TYPES = ("commune", "epci", "departement", "region")

# What api-partenaires accepts as a fiche (it checks the id against DILA). Stricter
# on the path than theirs: the URL is imported data written unquoted into a file
# that gates authentication, so no whitespace, quote or YAML metacharacter may pass.
_FICHE_URL_RE = re.compile(
    r"https://lannuaire\.service-public\.gouv\.fr/[A-Za-z0-9._~%/-]+/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def valid_fiche_url(url) -> bool:
    """Whether a Service-Public URL is safe and shaped like an api-partenaires fiche."""
    return isinstance(url, str) and bool(_FICHE_URL_RE.fullmatch(url))


def valid_siret(siret) -> bool:
    """Whether a value is a SIRET: exactly 14 ASCII digits."""
    return isinstance(siret, str) and bool(re.fullmatch(r"[0-9]{14}", siret))


def domain_bucket(organization: Organization, key: str) -> list[str]:
    """Return one normalized ``proconnect_domains`` bucket for an org."""
    value = organization.proconnect_domains
    return normalize_domains(value.get(key)) if isinstance(value, dict) else []


def _normalized_buckets(value) -> dict:
    """All normalized buckets of a raw ``proconnect_domains`` value."""
    if not isinstance(value, dict):
        return {key: [] for key in PROCONNECT_DOMAIN_BUCKETS}
    return {key: normalize_domains(value.get(key)) for key in PROCONNECT_DOMAIN_BUCKETS}


def proconnect_domains(organization: Organization) -> dict:
    """Return all normalized buckets: ``{requested, manual, dpnt, candidates, discarded}``."""
    return _normalized_buckets(organization.proconnect_domains)


def update_proconnect_domains(organization: Organization, **overrides):
    """Atomically merge bucket overrides into an org's ``proconnect_domains``.

    Read-modify-write on the JSON field would let a cron writing one bucket clobber
    a concurrent edit of another. We lock the row (``SELECT FOR UPDATE``) and re-read
    inside the transaction so concurrent writers serialize instead of losing updates.
    Example: ``update_proconnect_domains(org, candidates=["x.fr"])`` replaces only candidates.

    Invariant: a DILA (``dpnt``) domain is authoritative — once it's declared on
    service-public.gouv.fr it must live in ``dpnt`` ONLY, so any copy in
    ``manual``/``requested``/``candidates`` is stripped on every write. That's the
    end state the dpnt import drives toward (a domain "graduating" to ``dpnt``).

    Returns ``(previous, new)`` bucket dicts and syncs the passed instance.
    """
    unknown = set(overrides) - set(PROCONNECT_DOMAIN_BUCKETS)
    if unknown:
        # A typo'd kwarg would otherwise silently create a junk bucket that every
        # reader ignores — and that the caller believes it wrote.
        raise ValueError(
            f"Unknown proconnect_domains bucket(s): {', '.join(sorted(unknown))}"
        )
    with transaction.atomic():
        locked = Organization.objects.select_for_update().get(pk=organization.pk)
        previous = proconnect_domains(locked)
        new_value = dict(previous)
        for key, value in overrides.items():
            new_value[key] = normalize_domains(value)
        dpnt_set = set(new_value["dpnt"])
        if dpnt_set:
            for bucket in ("manual", "requested", "candidates"):
                new_value[bucket] = [d for d in new_value[bucket] if d not in dpnt_set]
        if new_value != previous:
            locked.proconnect_domains = new_value
            locked.save(update_fields=["proconnect_domains", "updated_at"])
    organization.proconnect_domains = new_value
    return previous, new_value


def routed_domains(
    organization: Organization, idp_id: Optional[str] = None
) -> set[str]:
    """Domains currently routed by the org's active ProConnect subscriptions.

    When ``idp_id`` is given, only subscriptions resolving to that provider are
    counted — so the allowlist's "routed" (live) set for an idp is exactly what
    :func:`idp_routed_domains` would push there, never another provider's domains.
    """
    domains: set[str] = set()
    for subscription in organization.service_subscriptions.all():
        if subscription.service.type != "proconnect" or not subscription.is_active:
            continue
        if idp_id is not None and subscription_idp_id(subscription) != idp_id:
            continue
        domains |= set(normalize_domains((subscription.metadata or {}).get("domains")))
    return domains


def domain_provenances(
    organization: Organization, idp_id: Optional[str] = None
) -> dict[str, str]:
    """Map each domain the org may route to where it came from.

    THE routable rule, written once — the allowlist build, the API payload and the
    UI all read it from here:

    - a domain is routable when it is live (``routed``) or sits in ``candidates``,
      ``manual`` or ``dpnt``;
    - a discard hides a candidate or a manual domain;
    - a discard never hides a DILA (``dpnt``) domain: service-public.gouv.fr is
      authoritative;
    - a discard never hides a live one either: dropping a domain the provider is
      actively using would cut off its users.

    ``requested`` is not routable — it is a pending ask, not a decision.

    The value is the highest-priority provenance (:data:`ROUTABLE_PROVENANCES`).
    With ``idp_id``, "routed" means routed *to that provider*, so one provider's
    allowlist never inherits another's live domains.
    """
    return _provenances(
        proconnect_domains(organization), routed_domains(organization, idp_id)
    )


def _provenances(buckets: dict, routed: set[str]) -> dict[str, str]:
    """The rule of :func:`domain_provenances`, on already normalized inputs."""
    sources = {
        "routed": routed,
        "candidates": set(buckets["candidates"]),
        "manual": set(buckets["manual"]),
        "dpnt": set(buckets["dpnt"]),
    }
    hidden = set(buckets["discarded"]) - sources["dpnt"] - sources["routed"]

    provenances: dict[str, str] = {}
    for provenance in ROUTABLE_PROVENANCES:
        for domain in sources[provenance] - hidden:
            provenances[domain] = provenance
    return provenances


def routable_domains(
    organization: Organization, idp_id: Optional[str] = None
) -> list[str]:
    """The domains the org may route, sorted. See :func:`domain_provenances`."""
    return sorted(domain_provenances(organization, idp_id))


def known_domains(organization: Organization) -> set[str]:
    """Every domain we hold for the org, routable or not.

    The union of all five buckets plus what is live — i.e. exactly the rows the UI
    displays, including the pending asks and the discarded ones. Use
    :func:`routable_domains` for what may actually be routed.
    """
    domains = routed_domains(organization)
    for names in proconnect_domains(organization).values():
        domains.update(names)
    return domains


def _config_idp_id(config) -> Optional[str]:
    return (config or {}).get("idp_id")


def service_idp_id(service: Service) -> Optional[str]:
    """The ``idp_id`` of a service. Operators cannot override it."""
    return _config_idp_id(service.config)


def subscription_idp_id(subscription: ServiceSubscription) -> Optional[str]:
    """The ``idp_id`` a subscription routes to: its service's."""
    return service_idp_id(subscription.service)


def routed_domains_by_idp() -> dict[str, list[str]]:
    """Every provider's routed domains, grouped in a single pass.

    ``{idp_id: sorted domains}`` over all active ProConnect subscriptions, each
    resolved through :func:`subscription_idp_id`. For anything that walks several
    providers (the reconciliation and drift commands), this replaces one full scan
    per provider with one scan total.
    """
    grouped: dict[str, set[str]] = defaultdict(set)
    subscriptions = ServiceSubscription.objects.filter(
        service__type="proconnect", is_active=True
    ).select_related("service")

    for subscription in subscriptions:
        idp_id = subscription_idp_id(subscription)
        if not idp_id:
            continue
        grouped[idp_id].update(
            normalize_domains((subscription.metadata or {}).get("domains"))
        )

    return {idp_id: sorted(domains) for idp_id, domains in grouped.items()}


def idp_routed_domains(idp_id: str) -> list[str]:
    """The domains routed to a provider: what we push to it.

    The sorted, normalized union of the routed domains of every active ProConnect
    subscription resolving to ``idp_id``.

    Callers that need several providers should use :func:`routed_domains_by_idp`
    instead; this one is for the push path, which recomputes the set under the
    provider's lock so that what it PATCHes matches the DB at push time.
    """
    return routed_domains_by_idp().get(idp_id, [])


def sync_proconnect_provider(
    idp_id: str, client=None, raise_on_error: bool = False
) -> dict:
    """Compute the full domain list for ``idp_id`` and PATCH it to api-partenaires.

    Serialized per provider (see :func:`core.services.locks.lock_idp`). Returns a result dict. By
    default failures are logged and never raised. With ``raise_on_error=True``, a
    failed PATCH raises ``ProConnectPartnersError`` (so the caller can roll back
    its transaction). A not-configured client is always a silent skip, never an
    error.
    """
    client = client or ProConnectPartnersClient()
    if not client.is_configured:
        logger.info(
            "Skipping ProConnect domains push for idp %s: api-partenaires not configured",
            idp_id,
        )
        return {"idp_id": idp_id, "success": False, "skipped": True}

    with transaction.atomic():
        lock_idp(idp_id)
        domains = idp_routed_domains(idp_id)
        try:
            result = client.set_attached_email_domains(idp_id, domains)
        except ProConnectPartnersError as e:
            logger.error("Failed to push ProConnect domains for idp %s: %s", idp_id, e)
            # Report it even when we swallow it: with raise_on_error=False nothing
            # downstream ever sees this failure otherwise.
            sentry_sdk.capture_exception(e)
            if raise_on_error:
                raise
            return {
                "idp_id": idp_id,
                "success": False,
                "error": str(e),
                "domains": domains,
            }

    logger.info("Pushed ProConnect domains for idp %s: %s", idp_id, domains)
    return {"idp_id": idp_id, "success": True, "domains": domains, "result": result}


def sync_proconnect_provider_for_subscription(
    subscription: ServiceSubscription, raise_on_error: bool = False
) -> Optional[dict]:
    """Resolve a subscription's ``idp_id`` and push its provider's full domain list."""
    idp_id = subscription_idp_id(subscription)
    if not idp_id:
        logger.warning(
            "ProConnect subscription %s has no idp_id; skipping domains push",
            subscription.pk,
        )
        return None
    return sync_proconnect_provider(idp_id, raise_on_error=raise_on_error)


# ---------------------------------------------------------------------------
# Drift detection and the Service.out_of_sync flag.
# ---------------------------------------------------------------------------


class ProviderDrift(NamedTuple):
    """How a provider's live domains differ from what we intend to route."""

    missing: list[str]  # we route it, the provider lacks it
    unexpected: list[str]  # the provider serves it, we do not route it


class DriftReport(NamedTuple):
    """Outcome of :func:`check_providers_drift`."""

    drifted: dict[str, ProviderDrift]
    in_sync: dict[str, int]  # idp_id -> number of domains
    unreadable: dict[str, ProConnectPartnersError]


def provider_drift(idp_id: str, client, intended: list[str]) -> Optional[ProviderDrift]:
    """Compare ``intended`` with the provider's live domains; ``None`` when equal.

    Raises ``ProConnectPartnersError`` when the provider cannot be read.
    """
    config = client.get_configuration(idp_id)
    # Normalize both sides the same way, or a value the provider accepts but we
    # would never store reads as permanent drift.
    live = normalize_domains(config.get(ATTACHED_EMAIL_DOMAINS_KEY) or [])
    if live == intended:
        return None
    return ProviderDrift(
        missing=sorted(set(intended) - set(live)),
        unexpected=sorted(set(live) - set(intended)),
    )


def check_providers_drift(idp_ids, client, routed=None) -> DriftReport:
    """Check each provider against the DB. Read-only on the provider.

    ``routed`` is :func:`routed_domains_by_idp` when the caller already has it.
    A provider that looks drifted is checked again under its push lock before it
    is reported: a request that pushed but has not committed yet would otherwise
    read as drift, and drift blocks writes.
    """
    routed = routed_domains_by_idp() if routed is None else routed
    drifted, in_sync, unreadable = {}, {}, {}
    for idp_id in sorted(idp_ids):
        try:
            drift = provider_drift(idp_id, client, routed.get(idp_id, []))
            if drift:
                with transaction.atomic():
                    lock_idp(idp_id)
                    drift = provider_drift(idp_id, client, idp_routed_domains(idp_id))
        except ProConnectPartnersError as exc:
            sentry_sdk.capture_exception(exc)
            unreadable[idp_id] = exc
            continue
        if drift:
            drifted[idp_id] = drift
        else:
            in_sync[idp_id] = len(routed.get(idp_id, []))
    return DriftReport(drifted, in_sync, unreadable)


def service_idp_ids() -> dict[int, str]:
    """``{service id: idp_id}`` for the ProConnect services that have one."""
    return {
        service.pk: idp_id
        for service in Service.objects.filter(type="proconnect")
        if (idp_id := service_idp_id(service))
    }


def out_of_sync_idp_ids() -> set[str]:
    """The providers of the services currently flagged ``out_of_sync``."""
    flagged = set(
        Service.objects.filter(type="proconnect", config__out_of_sync=True).values_list(
            "pk", flat=True
        )
    )
    return {
        idp_id
        for service_id, idp_id in service_idp_ids().items()
        if service_id in flagged
    }


def update_out_of_sync(report: DriftReport) -> None:
    """Set ``config["out_of_sync"]`` of the services from a drift report.

    A service is out of sync when its provider drifted, and back in sync when the
    provider was read and matches. A provider the report does not cover, or could
    not read, changes nothing.
    """
    # Row-locked: this rewrites the whole config, which an admin may edit too. The
    # provider is read from the locked row, so a service moved to another provider
    # meanwhile is judged by the one it has now.
    with transaction.atomic():
        for service in (
            Service.objects.select_for_update().filter(type="proconnect").order_by("pk")
        ):
            idp_id = service_idp_id(service)
            if idp_id in report.drifted:
                flagged = True
            elif idp_id in report.in_sync:
                flagged = False
            else:
                continue
            if service.out_of_sync == flagged:
                continue
            config = dict(service.config or {})
            if flagged:
                config["out_of_sync"] = True
            else:
                config.pop("out_of_sync", None)
            Service.objects.filter(pk=service.pk).update(config=config)


def refresh_out_of_sync(idp_ids, client=None) -> Optional[DriftReport]:
    """Recheck providers and update the flags; ``None`` when not configured."""
    client = client or ProConnectPartnersClient()
    if not client.is_configured:
        return None
    report = check_providers_drift(idp_ids, client)
    update_out_of_sync(report)
    return report


# ---------------------------------------------------------------------------
# Deployed-allowlist pre-validation cache.
#
# The *deployed* api-partenaires allowlist (a file in their repo, updated by PR)
# lags our generated one, and their PATCH rejects any domain not yet in it. We fetch
# it (``proconnect_fetch_prevalidated``) and cache the allowed domains per idp so the
# UI can flag which of an org's domains are already routable vs pending the deploy.
#
# The whole ``{uid: [domains]}`` map lives under ONE key, and the values are lists
# (not native redis SETs, which can't represent an empty-but-defined allowlist).
# One key because the file is authoritative for every provider at once: a uid it
# does not mention has nothing deployed, which is only distinguishable from "we
# never fetched the file" if the map is written and expires atomically.
# ---------------------------------------------------------------------------

PREVALIDATED_CACHE_KEY = "proconnect_idps_allowed_fqdns"


def _allowlist_cache():
    """The cache holding the fetched deployed allowlist.

    Reuse ``SESSION_CACHE_ALIAS`` — in every environment it already points at the
    real shared cache (redis in dev/prod, locmem in tests), never the no-op
    DummyCache that some envs use as their ``default``. The fetch command and the
    web process must share it, so a per-process cache won't do.
    """
    return caches[settings.SESSION_CACHE_ALIAS]


def get_prevalidated_allowlist() -> Optional[dict]:
    """The whole cached deployed allowlist ``{idp_id: [domains]}``.

    ``None`` means no fetch has landed (or its TTL expired) — pre-validation is
    unknown for every provider. Anything else means the file was read, so it is
    authoritative about which uids have a deployed allowlist and which don't.
    """
    cached = _allowlist_cache().get(PREVALIDATED_CACHE_KEY)
    return cached if isinstance(cached, dict) else None


def store_prevalidated_allowlist(allowlist: dict) -> dict:
    """Cache the deployed allowlist (normalized values; TTL from settings)."""
    cleaned = {uid: normalize_domains(domains) for uid, domains in allowlist.items()}
    _allowlist_cache().set(
        PREVALIDATED_CACHE_KEY,
        cleaned,
        timeout=settings.PROCONNECT_DOMAIN_ALLOWLIST_CACHE_TTL,
    )
    return cleaned


def store_prevalidated_domains(idp_id: str, domains) -> list[str]:
    """Cache one idp's deployed allowlist, keeping the other idps' entries."""
    allowlist = dict(get_prevalidated_allowlist() or {})
    allowlist[idp_id] = domains
    return store_prevalidated_allowlist(allowlist)[idp_id]


def get_prevalidated_domains(idp_id: str) -> Optional[list]:
    """An idp's deployed allowlist, or ``None`` when none has been fetched at all.

    An idp the fetched allowlist does not mention has nothing deployed: ``[]``,
    not unknown. api-partenaires would reject every domain pushed there.
    """
    allowlist = get_prevalidated_allowlist()
    if allowlist is None:
        return None
    return allowlist.get(idp_id, [])


def operator_prevalidated_allowlists(operator_id) -> dict:
    """Map each of the operator's ProConnect idps to its prevalidated allowlist
    (``{idp_id: frozenset(domains)}``) — the deployed set from
    :func:`get_prevalidated_domains`.

    Every one of the operator's idps gets an entry once *any* allowlist has been
    fetched: one absent from the fetched file has nothing deployed (empty), which
    is not the same as the unknown we report when no fetch has landed at all — then
    the map is empty and no idp gets a verdict.

    Computed once per request (one query + one cache read) so the org serializer
    stays N+1-free. An allowlist is per-idp: the same domain can be deployed on one
    provider and pending on another.
    """
    result = {}
    if not operator_id:
        return result
    allowlist = get_prevalidated_allowlist()
    if allowlist is None:
        return result
    idps = set()
    for config in OperatorServiceConfig.objects.filter(
        operator_id=operator_id, service__type="proconnect"
    ).select_related("service"):
        idp = service_idp_id(config.service)
        if idp:
            idps.add(idp)

    for idp in idps:
        result[idp] = frozenset(allowlist.get(idp) or ())
    return result


def prevalidated_org_domains(organization, prevalidated_allowlists) -> Optional[dict]:
    """Per-idp intersection of :func:`known_domains` with each deployed allowlist.

    Every domain we display gets a verdict, not just the routable ones: a superuser
    deciding on a pending ask needs to know whether validating it would route now
    or only after the next allowlist deploy.

    ``prevalidated_allowlists`` is ``operator_prevalidated_allowlists(...)``. Returns
    ``{idp_id: sorted(known ∩ allowed)}`` for each idp with a known allowlist, or
    ``None`` when none is known (→ "pre-validation unknown"). An idp mapping to
    ``[]`` means "defined, but nothing pre-validated".
    """
    if not prevalidated_allowlists:
        return None
    domains = known_domains(organization)
    return {
        idp: sorted(domains & allowed)
        for idp, allowed in prevalidated_allowlists.items()
    }


# ---------------------------------------------------------------------------
# Allowlist (oidc_providers.*.yaml) generation
#
# The api-partenaires allowlist YAML declares, per provider (uid = idp_id), the
# ``allowed_attached_email_domains`` a partner may route. We regenerate it from DB
# data so it stays a superset of everything we may push.
# ---------------------------------------------------------------------------


def org_rpnt_valid_domains(organization: Organization) -> set[str]:
    """The org's RPNT-valid domains — website and email — as a set.

    The criteria live on the model (``rpnt_valid_site_domain`` /
    ``rpnt_valid_mail_domain``, also what ``get_mail_domain_status`` picks from);
    this is the set view of them, which the ``dpnt`` bucket caches.
    """
    domains = {
        organization.rpnt_valid_site_domain,
        organization.rpnt_valid_mail_domain,
    }
    return {d.strip().lower() for d in domains if d and d.strip()}


def _proconnect_idp_scopes() -> dict[str, dict]:
    """Map each ``idp_id`` to the operators and services that route to it.

    Each value is ``{"operator_ids": set, "service_ids": set}``.
    """
    services = list(Service.objects.filter(type="proconnect"))
    services_by_id = {service.id: service for service in services}
    scopes: dict[str, dict] = defaultdict(
        lambda: {"operator_ids": set(), "service_ids": set()}
    )

    def _add(idp_id, operator_id, service_id):
        if idp_id:
            scopes[idp_id]["operator_ids"].add(operator_id)
            scopes[idp_id]["service_ids"].add(service_id)

    # Every operator that has a proconnect service configured.
    for config in OperatorServiceConfig.objects.filter(service__in=services):
        service = services_by_id[config.service_id]
        _add(service_idp_id(service), config.operator_id, config.service_id)

    # Operators routing via an active subscription (covers those with no config row).
    for subscription in ServiceSubscription.objects.filter(
        service__in=services, is_active=True
    ):
        service = services_by_id[subscription.service_id]
        _add(service_idp_id(service), subscription.operator_id, service.id)

    return scopes


def _covered_departement_codes(operator_ids) -> set[str]:
    """Départements covered by the given operators, from their ``config["departements"]``.

    Coverage is the operator's declared reference scope, NOT the départements of
    the organizations it currently manages.
    """
    codes: set[str] = set()
    for config in Operator.objects.filter(id__in=list(operator_ids)).values_list(
        "config", flat=True
    ):
        for code in (config or {}).get("departements") or []:
            if isinstance(code, str) and code.strip():
                # Matched against Organization.departement_code_insee, stored
                # uppercase for Corsica ("2A"/"2B").
                codes.add(code.strip().upper())
    return codes


def _scoped_organization_ids(operator_ids, service_ids) -> set:
    """Ids of the organizations whose domains feed a provider's allowlist.

    For the operators/services resolving to a given idp, this is the union of:
    - orgs in one of the operators' declared ``config["departements"]``,
    - orgs the operators currently manage (OperatorOrganizationRole),
    - any org with an active subscription to one of the services under one of
      the operators.
    """
    operator_ids = list(operator_ids)
    covered = _covered_departement_codes(operator_ids)

    query = Q(
        service_subscriptions__service_id__in=service_ids,
        service_subscriptions__is_active=True,
        service_subscriptions__operator_id__in=operator_ids,
    )
    if covered:
        query |= Q(departement_code_insee__in=covered)
    if operator_ids:
        query |= Q(operators__in=operator_ids)
    return set(
        Organization.objects.filter(query).distinct().values_list("pk", flat=True)
    )


def build_proconnect_allowlist() -> list[dict]:
    """Build the allowlist entries for every ProConnect provider.

    Each provider's ``allowed_attached_email_domains`` is the union of the routable
    domains (:func:`domain_provenances`) of every organization in scope. Each is a
    ``{domain, source, fiche, siret}`` item: ``source`` is one of
    :data:`ALLOWLIST_SOURCES`, ``fiche`` the organization's Service-Public URL
    (always on a ``dila`` row, otherwise when the organization is of a type in
    :data:`FICHE_ORG_TYPES`) and ``siret`` its SIRET when it has a valid one.
    """
    return list(iter_proconnect_allowlist())


class _DomainOwner(NamedTuple):
    """The organization whose provenance wins a domain in the allowlist build."""

    rank: tuple[bool, bool, int]
    provenance: str
    fiche_url: Optional[str]
    org_name: str
    siret: Optional[str]
    org_type: str


def dila_domain_owners() -> dict[str, set]:
    """Map every ``dpnt`` (DILA) domain to the ids of the organizations declaring it.

    One query over every organization, whatever provider it is scoped to.
    """
    owners: dict[str, set] = defaultdict(set)
    rows = Organization.objects.exclude(proconnect_domains={}).values_list(
        "pk", "proconnect_domains"
    )
    for pk, buckets in rows.iterator():
        if isinstance(buckets, dict):
            for domain in normalize_domains(buckets.get("dpnt")):
                owners[domain].add(pk)
    return owners


def _live_domains() -> tuple[dict, dict[str, set[str]]]:
    """What the active ProConnect subscriptions route, from a single scan.

    Returns ``({organization id: {idp_id: domains}}, {domain: idp_ids})``: what
    each organization routes to each provider, and every provider each live
    domain is routed to (see :func:`routed_domains_by_idp`).
    """
    by_organization: dict = {}
    by_domain: dict[str, set[str]] = defaultdict(set)
    rows = ServiceSubscription.objects.filter(
        service__type="proconnect", is_active=True
    ).values_list("organization_id", "metadata", "service__config")
    for organization_id, metadata, config in rows:
        idp_id = _config_idp_id(config)
        if not idp_id:
            continue
        domains = normalize_domains((metadata or {}).get("domains"))
        by_organization.setdefault(organization_id, {}).setdefault(
            idp_id, set()
        ).update(domains)
        for domain in domains:
            by_domain[domain].add(idp_id)
    return by_organization, by_domain


# Ids per query when fetching the organizations in scope.
ORGANIZATION_CHUNK = 2000


def _iter_scoped_organizations(organization_ids):
    """Yield the in-scope organizations in pk order, as plain row tuples.

    ``(pk, proconnect_domains, service_public_url, name, siret, type)``: nothing
    else of the model is read, and no model instance is built.
    """
    ordered = sorted(organization_ids)
    for start in range(0, len(ordered), ORGANIZATION_CHUNK):
        yield from (
            Organization.objects.filter(
                pk__in=ordered[start : start + ORGANIZATION_CHUNK]
            )
            .order_by("pk")
            .values_list(
                "pk",
                "proconnect_domains",
                "service_public_url",
                "name",
                "siret",
                "type",
            )
        )


def iter_proconnect_allowlist():
    """Yield the entries of :func:`build_proconnect_allowlist`, one provider at a time.

    Entries come in ``uid`` order and each provider's rows are released as soon as
    it is yielded, so a caller that streams them never holds the whole file.
    """
    # Global, not per provider: a domain can be taken by an organization this
    # provider is not scoped to.
    dila_owners = dila_domain_owners()
    live_by_organization, live_idps = _live_domains()
    scopes = _proconnect_idp_scopes()

    # An organization in the scope of several providers is read once, not once per
    # provider.
    idps_by_organization: dict = defaultdict(list)
    for idp_id, scope in scopes.items():
        for organization_id in _scoped_organization_ids(
            scope["operator_ids"], scope["service_ids"]
        ):
            idps_by_organization[organization_id].append(idp_id)

    domain_info: dict[str, dict[str, _DomainOwner]] = {idp_id: {} for idp_id in scopes}
    live_domains: dict[str, set[str]] = {idp_id: set() for idp_id in scopes}
    # In pk order, so that each provider sees its organizations the way a walk of
    # its own would: homonyms tie on name, and a tie on a domain goes to the first
    # organization walked.
    for pk, value, fiche_url, name, siret, org_type in _iter_scoped_organizations(
        idps_by_organization
    ):
        buckets = _normalized_buckets(value)
        routed = live_by_organization.get(pk, {})
        for idp_id in idps_by_organization[pk]:
            # Per-idp, so this org only contributes what it routes to THIS provider.
            org_live = routed.get(idp_id, set())
            live_domains[idp_id] |= org_live
            info = domain_info[idp_id]
            for domain, provenance in _provenances(buckets, org_live).items():
                if provenance in ("candidates", "manual"):
                    # Already live on another provider: it would be rejected as taken.
                    if live_idps.get(domain, set()) - {idp_id}:
                        continue
                if provenance == "candidates":
                    # A guess must not land on a domain DILA gives to another
                    # collectivité (a homonym), in or out of this provider's scope.
                    if dila_owners.get(domain, set()) - {pk}:
                        continue
                # Two organizations can claim the same domain (homonyms). The row
                # takes its fiche and SIRET from the one DILA gives it to, else
                # the one routing it, else the strongest provenance; a full tie
                # goes to the first walked.
                rank = (
                    provenance == "dpnt",
                    domain in org_live,
                    ROUTABLE_PROVENANCES.index(provenance),
                )
                current = info.get(domain)
                if current is None or rank > current.rank:
                    info[domain] = _DomainOwner(
                        rank,
                        provenance,
                        fiche_url or None,
                        name or "",
                        siret or None,
                        org_type,
                    )

    fiche_is_valid: dict = {}
    for idp_id in sorted(scopes):
        info = domain_info.pop(idp_id)
        live = live_domains.pop(idp_id)
        # Ordered by organization name ASC, then domain ASC.
        allowed = []
        for domain, owner in sorted(
            info.items(), key=lambda kv: (kv[1].org_name.casefold(), kv[0])
        ):
            has_fiche = fiche_is_valid.get(owner.fiche_url)
            if has_fiche is None:
                has_fiche = fiche_is_valid[owner.fiche_url] = valid_fiche_url(
                    owner.fiche_url
                )
            # A live domain is "routed" even when DILA declares it: api-partenaires
            # checks every "dila" row against DILA and refuses the ones that fail
            # (shared domain, name not carried...), while "routed" is accepted as is.
            # A DILA domain without a usable fiche cannot be "dila" for
            # api-partenaires: it falls through to the next source.
            if domain in live:
                source = ALLOWLIST_SOURCE_ROUTED
            elif owner.provenance == "dpnt" and has_fiche:
                source = ALLOWLIST_SOURCE_DILA
            elif owner.provenance == "manual":
                source = ALLOWLIST_SOURCE_MANUAL
            else:
                source = ALLOWLIST_SOURCE_CANDIDATE
            # Every row carries its fiche when the organization is one that has
            # one (a commune, an EPCI...); a "dila" row always does.
            with_fiche = source == ALLOWLIST_SOURCE_DILA or (
                has_fiche and owner.org_type in FICHE_ORG_TYPES
            )
            allowed.append(
                {
                    "domain": domain,
                    "source": source,
                    "fiche": owner.fiche_url if with_fiche else None,
                    "siret": owner.siret if valid_siret(owner.siret) else None,
                }
            )
        yield {"uid": idp_id, ALLOWED_DOMAINS_KEY: allowed}


# Lines per chunk of the streamed YAML.
YAML_CHUNK_LINES = 5000


def _allowlist_yaml_lines(entries):
    """The lines of :func:`render_proconnect_allowlist_yaml`, one at a time."""
    yield "oidc_providers:"
    for entry in entries:
        # json.dumps yields a valid double-quoted YAML scalar (JSON is a YAML
        # subset), so a uid containing a quote or newline can't break out.
        yield f"  - uid: {json.dumps(entry['uid'])}"
        domains = entry[ALLOWED_DOMAINS_KEY]
        if not domains:
            yield f"    {ALLOWED_DOMAINS_KEY}: []"
            continue
        yield f"    {ALLOWED_DOMAINS_KEY}:"
        for item in domains:
            source = item["source"]
            if source not in ALLOWLIST_SOURCES:
                raise ValueError(f"Unknown allowlist source: {source!r}")
            # The domain itself is safe by construction: only normalize_domains()
            # values reach a bucket, and none of them can hold a space or a newline.
            yield f"      - domain: {item['domain']}"
            # Written unquoted: only a URL that passes the strict check may. A
            # "dila" row must have one, any other may.
            if item.get("fiche") or source == ALLOWLIST_SOURCE_DILA:
                if not valid_fiche_url(item.get("fiche")):
                    raise ValueError(f"Invalid fiche URL for {item['domain']}")
                yield f"        fiche: {item['fiche']}"
            # Quoted: bare, 14 digits would parse as a YAML integer. A SIRET is
            # optional (an organization may not have one); only 14 digits may be
            # written, so nothing else can reach the file.
            if item.get("siret"):
                if not valid_siret(item["siret"]):
                    raise ValueError(f"Invalid SIRET for {item['domain']}")
                yield f'        siret: "{item["siret"]}"'
            yield f"        source: {source}"


def iter_proconnect_allowlist_yaml(entries):
    """Render allowlist entries as YAML chunks, in the api-partenaires format.

    Each domain is a ``domain`` / ``fiche`` / ``siret`` / ``source`` mapping
    (``fiche`` required for ``dila``, optional otherwise; ``siret`` optional).
    The chunks, joined, are what :func:`render_proconnect_allowlist_yaml` returns.
    """
    chunk = []
    for line in _allowlist_yaml_lines(entries):
        chunk.append(line)
        if len(chunk) >= YAML_CHUNK_LINES:
            yield "\n".join(chunk) + "\n"
            chunk = []
    if chunk:
        yield "\n".join(chunk) + "\n"


def render_proconnect_allowlist_yaml(entries: list[dict]) -> str:
    """Render allowlist entries as YAML matching the api-partenaires format."""
    return "".join(iter_proconnect_allowlist_yaml(entries))
