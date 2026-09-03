"""Domains service: the organization's own domain names, and what serves their website.

Storage is the ``domains`` service subscription metadata (no dedicated model)::

    {
      "domains": ["exemple.fr", "autre.fr"],
      "website": {
        "exemple.fr": {"mode": "parking"},
        "autre.fr": {"mode": "dns_a", "target": "192.0.2.1"}
      }
    }

``domains`` is a normalized list (lowercased, deduped, sorted). ``website`` holds one
entry per declared domain: ``parking`` (a page we generate), an external server
pointed at by address records (target = comma-separated IPv4/IPv6, one ``A`` per
IPv4 and one ``AAAA`` per IPv6) or by a ``CNAME`` record (target = fqdn), an HTTP
redirection (target = https url), or ``none``.

Unrelated to ``Organization.proconnect_domains``, which is ProConnect routing data —
a domain declared here never reaches the ProConnect allowlist.
"""

import ipaddress
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

from core.models import ServiceSubscription
from core.services import dns as dns_service
from core.services.domainnames import is_valid_domain, normalize_domains

SERVICE_TYPE = "domains"

DOMAINS_KEY = "domains"
WEBSITE_KEY = "website"

MODE_NONE = "none"
MODE_PARKING = "parking"
MODE_DNS_A = "dns_a"
MODE_DNS_CNAME = "dns_cname"
MODE_REDIRECT_301 = "redirect_301"
MODE_REDIRECT_302 = "redirect_302"

WEBSITE_MODES = (
    MODE_NONE,
    MODE_PARKING,
    MODE_DNS_A,
    MODE_DNS_CNAME,
    MODE_REDIRECT_301,
    MODE_REDIRECT_302,
)
# Modes serving an HTTP redirection, permanent (301) or temporary (302).
MODES_REDIRECT = (MODE_REDIRECT_301, MODE_REDIRECT_302)
# Modes needing a target: the DNS record's value, or the redirection's url.
MODES_WITH_TARGET = (MODE_DNS_A, MODE_DNS_CNAME, *MODES_REDIRECT)
# What a domain failing RPNT 1.2 may still do: nothing, or redirect to the
# collectivité's official domain. We do not serve its website — our parking page or
# its own server — on an extension that is not sovereign.
MODES_WITHOUT_RPNT_1_2 = (MODE_NONE, *MODES_REDIRECT)

# Addresses per domain: enough for dual-stack and a couple of front-ends, not enough
# to turn the field into a zone editor.
MAX_ADDRESSES = 10

# Domain extensions accepted by RPNT criterion 1.2 ("nom de domaine souverain"),
# mapped to the départements where each one applies (INSEE codes; ``None`` for a
# nationwide extension). The mapping is what candidate generation needs
# (core/services/domains_candidates.py); the flat set below is what the 1.2 check
# needs. One list, transcribed once.
# https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#1.2
# Kept in sync with DOMAIN_EXTENSIONS_ALLOWED in suitenumerique/st-home
# (data/tasks/defs.py), which computes the rpnt criteria we import.
DOMAIN_EXTENSIONS_DEPARTEMENTS: dict[str, frozenset | None] = {
    # National
    "fr": None,
    # Régional
    "alsace": frozenset({"67", "68"}),
    "bzh": frozenset({"22", "29", "35", "44", "56"}),
    "corsica": frozenset({"2A", "2B"}),
    "paris": frozenset({"75"}),
    # Outre-mer
    "gp": frozenset({"971"}),  # Guadeloupe
    "mq": frozenset({"972"}),  # Martinique
    "gf": frozenset({"973"}),  # Guyane
    "re": frozenset({"974"}),  # Réunion
    "pm": frozenset({"975"}),  # Saint-Pierre-et-Miquelon
    "yt": frozenset({"976"}),  # Mayotte
    "wf": frozenset({"986"}),  # Wallis-et-Futuna
    "pf": frozenset({"987"}),  # Polynésie française
    "nc": frozenset({"988"}),  # Nouvelle-Calédonie
    # "bl",  # Saint-Barthélemy
    # "mf",  # Saint-Martin
}

# Never suggested as a candidate domain — ".eu" is supranational (it would be a
# candidate for every collectivité) and ".tf" has no communes — but both are
# conformant when a collectivité already uses one.
DOMAIN_EXTENSIONS_NOT_SUGGESTED = frozenset({"eu", "tf"})

# A domain outside this set is not RPNT 1.2 conformant, and we do not serve a
# parking page for it — that page is the collectivité's official web presence, so
# it belongs on a sovereign domain. An internationalized domain is refused too, on
# the extension being sovereign or not: see :func:`is_internationalized`.
DOMAIN_EXTENSIONS_ALLOWED = (
    frozenset(DOMAIN_EXTENSIONS_DEPARTEMENTS) | DOMAIN_EXTENSIONS_NOT_SUGGESTED
)


def domain_extension(domain) -> str:
    """The last label of a domain, lowercased (``""`` if there is none)."""
    if not isinstance(domain, str):
        return ""
    labels = domain.strip().lower().rstrip(".").rsplit(".", 1)
    return labels[-1] if len(labels) == 2 else ""


def is_internationalized(domain) -> bool:
    """Whether a domain is internationalized, in either of its two forms.

    ``stmearddegurçon.fr`` (unicode, a U-label) and ``xn--stmearddeguron-rjb.fr``
    (punycode, the A-label it encodes to) are the same name written two ways.
    """
    if not isinstance(domain, str):
        return False
    value = domain.strip().lower()
    if not value.isascii():
        return True
    return any(label.startswith("xn--") for label in value.split("."))


def is_rpnt_1_2_valid(domain) -> bool:
    """Whether a domain satisfies RPNT criterion 1.2 (sovereign domain extension).

    An internationalized domain never qualifies. It resolves and its extension may
    well be sovereign, but a name a citizen cannot type, read back or tell apart
    from a lookalike is not one a collectivité should publish as its official
    address.
    """
    if is_internationalized(domain):
        return False
    return domain_extension(domain) in DOMAIN_EXTENSIONS_ALLOWED


def allowed_modes(domain) -> tuple:
    """The website modes a domain may use, given its extension."""
    return WEBSITE_MODES if is_rpnt_1_2_valid(domain) else MODES_WITHOUT_RPNT_1_2


def default_mode(domain) -> str:
    """What serves a domain's website when nothing was configured for it.

    A parking page is the collectivité's official web presence, so we only generate
    one on an RPNT 1.2 conformant domain; anything else defaults to serving nothing
    until the user points it somewhere.
    """
    return MODE_PARKING if is_rpnt_1_2_valid(domain) else MODE_NONE


def redirect_url(target) -> str | None:
    """Normalize a redirection target to an https url, or ``None`` if unusable.

    A bare ``exemple.fr/page`` is read as a url rather than a path, and ``http`` is
    upgraded: we control the redirection we serve, so it always goes to https.
    """
    if not isinstance(target, str) or not target.strip():
        return None
    raw = target.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    # A "user:password@host" url displays as one host and resolves as another — the
    # classic phishing form, and never something a collectivité needs.
    if parsed.username or parsed.password:
        return None
    try:
        port = parsed.port
        host = (parsed.hostname or "").rstrip(".")
    except ValueError:
        return None
    if not is_valid_domain(host):
        return None
    # An IP address matches the hostname shape; a redirection to one is a mistake.
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, parsed.fragment))


def parse_addresses(target) -> list[str] | None:
    """Parse a comma-separated address list, or ``None`` if any of it is unusable.

    IPv4 and IPv6 share the field: the record type follows from the address family
    (one ``A`` per IPv4, one ``AAAA`` per IPv6), so there is nothing for the user to
    pick. Returns canonical forms, deduped, in the order given.
    """
    if not isinstance(target, str) or not target.strip():
        return None
    addresses: list[str] = []
    for raw in target.split(","):
        value = raw.strip()
        if not value:
            continue
        # A scoped address ("fe80::1%eth0") parses but means nothing in a zone.
        if "%" in value:
            return None
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return None
        # compressed() is the canonical form: "2001:0DB8::0001" -> "2001:db8::1".
        if address.compressed not in addresses:
            addresses.append(address.compressed)
    if not addresses or len(addresses) > MAX_ADDRESSES:
        return None
    return addresses


def is_valid_target(mode, target) -> bool:
    """Whether a target is valid for its mode.

    IP addresses for the address record, fqdn for a ``CNAME``, https url for a
    redirection.
    """
    if not isinstance(target, str) or not target.strip():
        return False
    value = target.strip().lower()
    if mode == MODE_DNS_A:
        return parse_addresses(target) is not None
    if mode == MODE_DNS_CNAME:
        # A trailing dot is a legitimate way to write an absolute name.
        name = value.rstrip(".")
        if not is_valid_domain(name):
            return False
        # An IP address matches the hostname shape but is not a valid CNAME target
        # — and picking CNAME then pasting an IP is the obvious mix-up to catch.
        try:
            ipaddress.ip_address(name)
        except ValueError:
            return True
        return False
    if mode in MODES_REDIRECT:
        return redirect_url(target) is not None
    return False


def normalize_target(mode, target) -> str:
    """Canonical form of a target for its mode.

    Callers must have checked it with :func:`is_valid_target` first.
    """
    if mode == MODE_DNS_A:
        return ", ".join(parse_addresses(target))
    if mode == MODE_DNS_CNAME:
        return target.strip().lower().rstrip(".")
    if mode in MODES_REDIRECT:
        return redirect_url(target)
    return target.strip()


def website_entry(raw, domain) -> dict:
    """Coerce one stored website value into ``{"mode"[, "target"]}``.

    Anything unusable (missing, wrong shape, unknown mode, a mode needing a target
    without a valid one, a mode the domain's extension does not allow) falls back to
    the domain's default mode rather than propagating junk to the export.
    """
    fallback = {"mode": default_mode(domain)}
    if not isinstance(raw, dict):
        return fallback
    mode = raw.get("mode")
    if mode not in allowed_modes(domain):
        return fallback
    if mode in MODES_WITH_TARGET:
        target = raw.get("target")
        if not is_valid_target(mode, target):
            return fallback
        return {"mode": mode, "target": normalize_target(mode, target)}
    return {"mode": mode}


def subscription_domains(
    subscription: ServiceSubscription,
) -> tuple[list[str], dict]:
    """Return ``(domains, website)`` for a domains subscription.

    ``website`` has exactly one entry per declared domain: entries for domains that
    were removed are dropped, missing ones fall back to the domain's default mode.
    """
    metadata = subscription.metadata or {}
    domains = normalize_domains(metadata.get(DOMAINS_KEY))
    stored = metadata.get(WEBSITE_KEY)
    stored = stored if isinstance(stored, dict) else {}
    website = {domain: website_entry(stored.get(domain), domain) for domain in domains}
    return domains, website


def _organization_payload(organization) -> dict:
    """The organization data a parking page needs to render."""
    return {
        "id": str(organization.id),
        "name": organization.name,
        "type": organization.type,
        "siret": organization.siret,
        "siren": organization.siren,
        "code_insee": organization.code_insee,
        "code_postal": organization.code_postal,
        "population": organization.population,
        "departement_code_insee": organization.departement_code_insee,
        "region_code_insee": organization.region_code_insee,
        "adresse_messagerie": organization.adresse_messagerie,
        "telephone": organization.telephone,
        "site_internet": organization.site_internet,
        "service_public_url": organization.service_public_url,
    }


def export_website(entry: dict) -> dict:
    """One stored website config as the export speaks it: what *we* serve.

    A domain pointing at an external server serves nothing of ours — its records
    say where it goes — so ``dns_a``/``dns_cname`` never leave the API. Callers
    distinguish "nothing configured" from "points elsewhere" on the records list,
    not on the mode.
    """
    if entry["mode"] in (MODE_DNS_A, MODE_DNS_CNAME):
        return {"mode": MODE_NONE}
    return dict(entry)


def website_records(entry: dict) -> list[dict]:
    """The DNS records to publish for a domain, from its website config.

    ``prefix`` is the record's name relative to the domain — always ``""`` (the
    apex) for now, since nothing declares a subdomain here yet.
    """
    mode = entry["mode"]
    if mode == MODE_DNS_A:
        return [
            {
                "prefix": "",
                # The record type follows from the address family, which is why the
                # user is never asked to pick between A and AAAA.
                "type": "AAAA" if ":" in address else "A",
                "value": address,
            }
            for address in parse_addresses(entry.get("target")) or []
        ]
    if mode == MODE_DNS_CNAME:
        return [{"prefix": "", "type": "CNAME", "value": entry["target"]}]
    return []


def export_domains() -> list[dict]:
    """Return every domain declared on an active ``domains`` subscription.

    One entry per domain, with what we serve for it (``website``), the DNS records
    to publish for it (``records``), its organization and the operator managing the
    subscription. Everything, in one snapshot: a consumer that only wants the parking
    pages filters on ``website["mode"]`` itself.
    """
    subscriptions = (
        ServiceSubscription.objects.filter(service__type=SERVICE_TYPE, is_active=True)
        .select_related("organization", "operator")
        .order_by("organization__name", "pk")
    )

    entries = []
    for subscription in subscriptions:
        domains, website = subscription_domains(subscription)
        organization = _organization_payload(subscription.organization)
        for domain in domains:
            entries.append(
                {
                    "domain": domain,
                    "website": export_website(website[domain]),
                    "records": website_records(website[domain]),
                    "updated_at": subscription.updated_at,
                    "organization": organization,
                    "operator": {
                        "id": str(subscription.operator_id),
                        "name": subscription.operator.name,
                    },
                }
            )
    return entries


def expected_nameservers() -> list[str]:
    """The nameservers a declared domain must be delegated to."""
    return sorted(
        {
            nameserver.strip().rstrip(".").lower()
            for nameserver in settings.DOMAINS_NAMESERVERS
            if nameserver and nameserver.strip()
        }
    )


def check_domains(domains: list[str]) -> list[dict]:
    """Check the delegation and the RPNT 1.2 conformance of each domain.

    One entry per domain, in the order given::

        {
          "domain": "exemple.fr",
          "nameservers": ["ns1.lst-domaines.fr", "ns2.lst-domaines.fr"],
          "nameservers_valid": true,
          "error": null,          # a dns.ERROR_* code when the lookup failed
          "rpnt_1_2_valid": true,
          "extension": "fr",
          "allowed_modes": ["none", "parking", …],
          "default_mode": "parking"
        }

    ``allowed_modes`` and ``default_mode`` are what the modal builds its website
    dropdown from, so the rules live here and are never restated in the frontend.

    ``nameservers_valid`` demands the exact expected set: an extra nameserver means
    part of the zone is served elsewhere, which is a misconfiguration too. The DNS
    lookups are live, so this is slow — never call it in a loop over subscriptions.
    """
    expected = set(expected_nameservers())
    resolved = dns_service.nameservers_batch(domains)

    results = []
    for domain in domains:
        found, error = resolved.get(domain, ([], dns_service.ERROR_UNKNOWN))
        results.append(
            {
                "domain": domain,
                "nameservers": found,
                "nameservers_valid": bool(found) and set(found) == expected,
                "error": error,
                "rpnt_1_2_valid": is_rpnt_1_2_valid(domain),
                "extension": domain_extension(domain),
                "allowed_modes": list(allowed_modes(domain)),
                "default_mode": default_mode(domain),
            }
        )
    return results
