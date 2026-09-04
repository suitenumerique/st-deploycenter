#!/usr/bin/env python3
"""
Validate changes to the ProConnect api-partenaires ``oidc_providers`` allowlist.

Intended to run manually or in GitHub CI on a pull request in the
proconnect-gouv/api-partenaires repository. It compares two versions of the
allowlist YAML (base vs head), and for every *added* fqdn decides whether it is
backed by the official DILA data (service-public.gouv.fr) or is a "manual" entry
that a human must review.

It then prints a readable Markdown report so reviewers can quickly clear the
DILA-backed rows and focus their attention on the manual ones.

Design goals: **auditable and dependency-light**. Only the standard library plus
PyYAML are used. The DILA source of truth is the same export that
suitenumerique/st-home consumes:

    https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/exports/json

Usage::

    python validate_proconnect_allowlist.py --base old.yaml --head new.yaml
    python validate_proconnect_allowlist.py --base old.yaml --head new.yaml --dila-json dila.json
"""

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from urllib.parse import urlparse

import yaml

DILA_EXPORT_URL = (
    "https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/catalog/"
    "datasets/api-lannuaire-administration/exports/json"
)


# --- domain helpers ----------------------------------------------------------


def domain_from_url(url):
    """Extract a bare hostname from a website URL ('https://www.x.fr/a' -> 'x.fr')."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).netloc or "").lower()
    host = host.split(":")[0]  # drop port
    if host.startswith("www."):
        host = host[4:]
    return host or None


def domain_from_email(email):
    """Extract the domain part of an email ('a@x.fr' -> 'x.fr')."""
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None


# --- DILA index --------------------------------------------------------------


def load_dila_records(dila_json_path):
    """Return the raw DILA records, from a local file or the live export."""
    if dila_json_path:
        with open(dila_json_path, encoding="utf-8") as handle:
            return json.load(handle)
    with urllib.request.urlopen(DILA_EXPORT_URL, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))


def _coerce_dila_values(raw):
    """Normalize a DILA multi-value field into a list of strings/dicts.

    The export may store these fields either JSON-encoded (a list, possibly of
    ``{"valeur": ...}`` dicts — as ``site_internet`` is) or as a plain
    ``;``-separated string (as ``adresse_courriel`` sometimes is). Accept both
    rather than assuming one shape, so a format difference can't silently produce
    garbage domains. A malformed record contributes nothing instead of crashing.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text[0] in "[{":
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return [text]
            return decoded if isinstance(decoded, list) else [decoded]
        return [part.strip() for part in text.split(";") if part.strip()]
    return [raw]


def build_dila_domain_index(records):
    """Map every DILA-declared domain -> list of {siret, name} that declare it.

    Website domains come from the ``site_internet`` field, email domains from
    ``adresse_courriel``. Each field may be JSON-encoded or ``;``-separated
    depending on the export; :func:`_coerce_dila_values` accepts both.
    """
    index = defaultdict(list)
    # domain -> sirets already indexed for it, so a record declaring the same
    # domain as both its website and its email is listed once, not twice.
    seen = defaultdict(set)

    for record in records:
        siret = record.get("siret") or ""
        name = record.get("nom") or ""
        owner = {"siret": siret, "name": name}

        def _add(domain, owner=owner, siret=siret):
            if domain and siret not in seen[domain]:
                seen[domain].add(siret)
                index[domain].append(owner)

        for site in _coerce_dila_values(record.get("site_internet")):
            value = site.get("valeur") if isinstance(site, dict) else site
            _add(domain_from_url(value))

        for email in _coerce_dila_values(record.get("adresse_courriel")):
            value = email.get("valeur") if isinstance(email, dict) else email
            _add(domain_from_email(value))

    return index


# --- allowlist parsing -------------------------------------------------------


def load_allowlist(path):
    """Parse an allowlist YAML into {uid: set(fqdns)} (comments are ignored)."""
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    providers = {}
    for entry in data.get("oidc_providers", []) or []:
        # A hand-edited allowlist may hold a scalar where a mapping is expected;
        # ignore it rather than crashing the CI report.
        if not isinstance(entry, dict):
            continue
        uid = entry.get("uid")
        fqdns = set(entry.get("allowed_fqdns") or [])
        if uid:
            providers[uid] = fqdns
    return providers


def load_allowlist_comments(path):
    """Map ``fqdn -> "Source: ... | <url>"`` from the inline YAML comments.

    Our generator emits ``- domain # Source: <src> | <Service-Public URL>``;
    yaml.safe_load drops those, so we read them line-by-line to surface the
    Service-Public link (the collectivité's page) in the report.
    """
    comments = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            domain, sep, comment = stripped[2:].partition("#")
            if sep:
                comments[domain.strip()] = comment.strip()
    return comments


def parse_source_comment(comment):
    """Split ``"Source: <src> | <url>"`` into ``(source, url)`` (either may be None)."""
    if not comment:
        return None, None
    text = comment.strip()
    if text.lower().startswith("source:"):
        text = text.split(":", 1)[1].strip()
    # Tolerate any spacing around the ``|`` separator (``a|b``, ``a | b``, ...).
    parts = re.split(r"\s*\|\s*", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip() or None, parts[1].strip() or None
    return text or None, None


SERVICE_PUBLIC_HOST = "service-public.gouv.fr"


def _is_service_public_url(url):
    """Whether a URL is an https link to service-public.gouv.fr (or a subdomain).

    Subdomains are allowed because that is where the collectivité fiches live
    (``lannuaire.service-public.gouv.fr/...``).
    """
    host = urlparse(url).hostname or ""
    return urlparse(url).scheme == "https" and (
        host == SERVICE_PUBLIC_HOST or host.endswith(f".{SERVICE_PUBLIC_HOST}")
    )


def _source_suffix(comment):
    """Render a comment as a Markdown suffix with a clickable Service-Public link.

    The comment comes from the allowlist file under review, i.e. from the very PR
    a reviewer is reading: only a genuine service-public.gouv.fr https URL becomes
    a link, so a crafted comment can't turn the report into a link to anywhere
    (``javascript:``, a lookalike host, ...). Anything else is shown verbatim as
    inline code.
    """
    source, url = parse_source_comment(comment)
    if url:
        prefix = f"Source: `{source}` · " if source else ""
        if _is_service_public_url(url):
            return f" — {prefix}[fiche Service-Public]({url})"
        return f" — {prefix}`{url}`"
    if source:
        return f" — Source: `{source}`"
    return ""


def diff_allowlists(base, head):
    """Yield (uid, added, removed) tuples for every provider present in either file."""
    for uid in sorted(set(base) | set(head)):
        before = base.get(uid, set())
        after = head.get(uid, set())
        yield uid, sorted(after - before), sorted(before - after)


# --- report ------------------------------------------------------------------


def build_report(base, head, dila_index, head_comments):
    """Return the Markdown report string."""
    lines = ["# ProConnect allowlist validation report", ""]
    backed_total = 0
    review_total = 0

    for uid, added, removed in diff_allowlists(base, head):
        if not added and not removed:
            continue
        lines.append(f"## Provider `{uid}`")

        backed = [(d, dila_index[d]) for d in added if d in dila_index]
        review = [d for d in added if d not in dila_index]
        backed_total += len(backed)
        review_total += len(review)

        if backed:
            lines.append(f"### DILA-backed additions ({len(backed)})")
            lines.append("_Declared on service-public.gouv.fr — safe to approve._")
            for domain, owners in backed:
                owner = owners[0]
                extra = f" _(+{len(owners) - 1} more)_" if len(owners) > 1 else ""
                lines.append(
                    f"- `{domain}` — {owner['name']} (SIRET {owner['siret']})"
                    f"{extra}{_source_suffix(head_comments.get(domain))}"
                )
            lines.append("")

        if review:
            lines.append(f"### Additions to review ({len(review)})")
            lines.append(
                "_Not found in the current DILA export — check the source below._"
            )
            for domain in review:
                lines.append(f"- `{domain}`{_source_suffix(head_comments.get(domain))}")
            lines.append("")

        if removed:
            lines.append(f"### Removed ({len(removed)})")
            for domain in removed:
                lines.append(f"- `{domain}`")
            lines.append("")

    if len(lines) == 2:
        lines.append("_No allowlist changes detected._")

    lines.append("")
    lines.append(
        f"**Summary:** {backed_total} DILA-backed, {review_total} to review."
    )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        # Keep the docstring's line breaks, indentation and long URLs readable.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base", required=True, help="Allowlist YAML before the change.")
    parser.add_argument("--head", required=True, help="Allowlist YAML after the change.")
    parser.add_argument(
        "--dila-json",
        default=None,
        help="Local DILA export JSON (defaults to downloading the live export).",
    )
    args = parser.parse_args()

    base = load_allowlist(args.base)
    head = load_allowlist(args.head)
    head_comments = load_allowlist_comments(args.head)
    dila_index = build_dila_domain_index(load_dila_records(args.dila_json))

    report = build_report(base, head, dila_index, head_comments)
    sys.stdout.write(report)


if __name__ == "__main__":
    main()
