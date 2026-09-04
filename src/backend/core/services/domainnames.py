"""What a domain name is, and how we write it down.

Shared by every feature that stores domains (the domains service, ProConnect
routing, candidate generation): one shape, one normal form, one way to report a
bad one. Nothing here knows about RPNT, services or subscriptions.
"""

import re

# A real domain name: at least two dot-separated labels, each alphanumeric with
# optional interior hyphens. Everything we store must match this — it is also what
# keeps a stored value from breaking out of the allowlist YAML we build by
# concatenation, so it is a security boundary as much as a shape check.
_HOSTNAME_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
)


# How many domains one list may hold — a declared list, a ProConnect bucket. Each
# is hand-curated by a collectivité or a superuser; anything near this is abuse.
MAX_DOMAINS = 100


def is_valid_domain(domain) -> bool:
    """Whether a value is a well-formed domain name once stripped and lowercased.

    The single source of truth for what may be stored — callers use it to *reject*
    bad input instead of letting :func:`normalize_domains` drop it silently.
    """
    if not isinstance(domain, str):
        return False
    return bool(_HOSTNAME_RE.fullmatch(domain.strip().lower()))


def normalize_domains(domains) -> list[str]:
    """Normalize a domain list: lowercase, stripped, **deduped, sorted**, valid only.

    Domain lists are semantically sets — order is never meaningful — so we store
    them canonically. This keeps equality checks (change detection, spurious-write
    avoidance) order- and duplicate-insensitive everywhere they are compared.
    """
    cleaned = set()
    for domain in domains or []:
        if is_valid_domain(domain):
            cleaned.add(domain.strip().lower())
    return sorted(cleaned)


def invalid_domains(domains) -> list[str]:
    """Return the strings of a list that are not well-formed domains (blanks ignored).

    Callers must have checked the list holds strings; anything else is a type error
    they report themselves.
    """
    return [
        domain
        for domain in domains
        if isinstance(domain, str) and domain.strip() and not is_valid_domain(domain)
    ]
