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

import hashlib
import hmac
import json
import logging
import re
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models import Prefetch, Q

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

# Payload key and error code carrying the provider's domain list.
ATTACHED_EMAIL_DOMAINS_KEY = "attached_email_domains"
DOMAIN_NOT_ALLOWED_ERROR = "attached_email_domain_not_allowed"

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
        self, base_url=None, secret=None, timeout=DEFAULT_TIMEOUT, proxy_url=None
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

    @property
    def is_configured(self) -> bool:
        """Whether both a base URL and a secret are available."""
        return bool(self.base_url and self.secret)

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
            response = requests.request(
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
                # could never authenticate. Treated as an error below.
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as e:
            raise ProConnectPartnersError(
                redact_credentials(f"{method} {path} failed: {e}")
            ) from e

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

# Human label per provenance, for the allowlist YAML comment.
PROVENANCE_LABELS = {"dpnt": "DILA"}

# Full RPNT compliance (no candidate domain is generated when all are satisfied).
RPNT_COMPLETE_CRITERIA = frozenset({"1.1", "1.2", "2.1", "2.2", "2.3"})


def domain_bucket(organization: Organization, key: str) -> list[str]:
    """Return one normalized ``proconnect_domains`` bucket for an org."""
    value = organization.proconnect_domains
    return normalize_domains(value.get(key)) if isinstance(value, dict) else []


def proconnect_domains(organization: Organization) -> dict:
    """Return all normalized buckets: ``{requested, manual, dpnt, candidates, discarded}``."""
    return {key: domain_bucket(organization, key) for key in PROCONNECT_DOMAIN_BUCKETS}


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


def is_rpnt_complete(organization: Organization) -> bool:
    """Whether the org satisfies the full RPNT criteria set (1.1/1.2/2.1/2.2/2.3)."""
    return RPNT_COMPLETE_CRITERIA.issubset(set(organization.rpnt or []))


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
    buckets = proconnect_domains(organization)
    sources = {
        "routed": routed_domains(organization, idp_id),
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


# ---------------------------------------------------------------------------
# Effective-config memo.
#
# ``OperatorServiceConfig.get_effective_service_config`` is one query per call and
# resolving an idp needs it per subscription — so a full scan (allowlist build,
# routed-domain computation) repeats it thousands of times. Memoize it, but ONLY inside an
# explicit block: a ContextVar set and reset by the context manager, so nothing
# is cached outside it and a stale config can never leak into a later request.
# ---------------------------------------------------------------------------

_effective_config_memo: ContextVar[Optional[dict]] = ContextVar(
    "proconnect_effective_config_memo", default=None
)


@contextmanager
def effective_config_memo():
    """Memoize effective service configs for the duration of the block only."""
    token = _effective_config_memo.set({})
    try:
        yield
    finally:
        _effective_config_memo.reset(token)


def _effective_service_config(service, operator) -> dict:
    """``get_effective_service_config``, memoized when inside a memo block."""
    memo = _effective_config_memo.get()
    if memo is None:
        return OperatorServiceConfig.get_effective_service_config(service, operator)
    key = (getattr(service, "id", None), getattr(operator, "id", None))
    if key not in memo:
        memo[key] = OperatorServiceConfig.get_effective_service_config(
            service, operator
        )
    return memo[key]


def subscription_idp_id(subscription: ServiceSubscription) -> Optional[str]:
    """Return the effective ``idp_id`` for a subscription (with operator overrides)."""
    effective_config = _effective_service_config(
        subscription.service, subscription.operator
    )
    return (effective_config or {}).get("idp_id")


def routed_domains_by_idp() -> dict[str, list[str]]:
    """Every provider's routed domains, grouped in a single pass.

    ``{idp_id: sorted domains}`` over all active ProConnect subscriptions, each
    resolved through :func:`subscription_idp_id` (so per-operator ``idp_id``
    overrides are honored). For anything that walks several providers — the
    reconciliation and drift commands — this replaces one full scan per provider
    with one scan total.
    """
    grouped: dict[str, set[str]] = defaultdict(set)
    subscriptions = ServiceSubscription.objects.filter(
        service__type="proconnect", is_active=True
    ).select_related("service", "operator")

    with effective_config_memo():
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
    ).select_related("service", "operator"):
        effective = _effective_service_config(config.service, config.operator)
        idp = (effective or {}).get("idp_id")
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
    """Map each **effective** ``idp_id`` to the operators and services that route to it.

    Mirrors the push path (:func:`subscription_idp_id`), which honors per-operator
    ``idp_id`` overrides — so the allowlist is keyed by the very idp we push to,
    not the service's base config idp. Each value is
    ``{"operator_ids": set, "service_ids": set}``.
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

    # Every operator that has a proconnect service configured (override or base).
    for config in OperatorServiceConfig.objects.filter(
        service__in=services
    ).select_related("operator"):
        service = services_by_id.get(config.service_id)
        effective = _effective_service_config(service, config.operator)
        _add((effective or {}).get("idp_id"), config.operator_id, config.service_id)

    # Operators routing via an active subscription (covers those with no config row).
    for subscription in ServiceSubscription.objects.filter(
        service__in=services, is_active=True
    ).select_related("service", "operator"):
        _add(
            subscription_idp_id(subscription),
            subscription.operator_id,
            subscription.service_id,
        )

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


def _scoped_organizations(operator_ids, service_ids):
    """Organizations whose domains feed a provider's allowlist.

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
    return (
        Organization.objects.filter(query)
        .distinct()
        # routed_domains() walks every org's subscriptions (and their service /
        # operator, to resolve the effective idp): prefetch to keep the allowlist
        # build from issuing three queries per organization.
        .prefetch_related(
            Prefetch(
                "service_subscriptions",
                queryset=ServiceSubscription.objects.select_related(
                    "service", "operator"
                ),
            )
        )
    )


def build_proconnect_allowlist() -> list[dict]:
    """Build the allowlist entries for every ProConnect provider.

    Each provider's ``allowed_attached_email_domains`` is the union of the routable
    domains (:func:`domain_provenances`) of every organization in scope, each with
    its provenance and its organization's Service-Public URL for an explanatory
    YAML comment.
    """
    with effective_config_memo():
        return _build_proconnect_allowlist()


def _build_proconnect_allowlist() -> list[dict]:
    """Body of :func:`build_proconnect_allowlist` (runs under the config memo)."""
    entries = []
    for idp_id, scope in _proconnect_idp_scopes().items():
        # domain -> (priority, provenance, service_public_url, org_name)
        domain_info: dict[str, tuple[int, str, Optional[str], str]] = {}
        organizations = _scoped_organizations(
            scope["operator_ids"], scope["service_ids"]
        )
        # An explicit chunk_size is required for .iterator() to honor the prefetch.
        for organization in organizations.iterator(chunk_size=500):
            sp_url = organization.service_public_url or None
            org_name = organization.name or ""
            # Per-idp, so this org only contributes what it routes to THIS provider.
            for domain, provenance in domain_provenances(organization, idp_id).items():
                # Two organizations can claim the same domain; the strongest
                # provenance wins, whatever order we walk them in.
                priority = ROUTABLE_PROVENANCES.index(provenance)
                current = domain_info.get(domain)
                if current is None or priority > current[0]:
                    domain_info[domain] = (priority, provenance, sp_url, org_name)

        # Ordered by organization name ASC, then domain ASC.
        allowed = [
            {
                "domain": domain,
                "source": PROVENANCE_LABELS.get(info[1], info[1]),
                "service_public_url": info[2],
            }
            for domain, info in sorted(
                domain_info.items(), key=lambda kv: (kv[1][3].casefold(), kv[0])
            )
        ]
        entries.append({"uid": idp_id, ALLOWED_DOMAINS_KEY: allowed})

    entries.sort(key=lambda entry: entry["uid"])
    return entries


def _yaml_comment_text(value) -> str:
    """One line of comment text: no newline can escape it into a YAML entry.

    The Service-Public URL is imported data (``core/tasks/dpnt.py`` writes it
    without ``full_clean()``, so ``URLField`` never validates it) and it is
    concatenated into a file that gates authentication. A value carrying a newline
    would add a line of its own choosing to the published allowlist.
    """
    return " ".join(str(value).split())


def render_proconnect_allowlist_yaml(entries: list[dict]) -> str:
    """Render allowlist entries as YAML matching the api-partenaires format.

    Each domain is followed by a ``# Source: <src> | <Service-Public URL>`` comment
    (the URL part is omitted when unknown).
    """
    lines = ["oidc_providers:"]
    for entry in entries:
        # json.dumps yields a valid double-quoted YAML scalar (JSON is a YAML
        # subset), so a uid containing a quote or newline can't break out.
        lines.append(f"  - uid: {json.dumps(entry['uid'])}")
        domains = entry[ALLOWED_DOMAINS_KEY]
        if not domains:
            lines.append(f"    {ALLOWED_DOMAINS_KEY}: []")
            continue
        lines.append(f"    {ALLOWED_DOMAINS_KEY}:")
        for item in domains:
            comment = f"Source: {_yaml_comment_text(item['source'])}"
            if item.get("service_public_url"):
                comment += f" | {_yaml_comment_text(item['service_public_url'])}"
            # The domain itself is safe by construction: only normalize_domains()
            # values reach a bucket, and none of them can hold a space or a newline.
            lines.append(f"      - {item['domain']}  # {comment}")
    return "\n".join(lines) + "\n"
