"""Candidate domains: the domain names we suggest a collectivité could own.

The generator turns a commune's name and département into the domains it plausibly
registered, so the ProConnect ``candidates`` bucket can propose them for validation.
It is a guess, not a fact: nothing here proves the collectivité owns the domain.

The spellings are not invented. They were chosen by replaying the generator against
the DPNT dataset (~24k domains that communes actually use, per RPNT criteria 1.1 and
2.1/2.2, on an RPNT 1.2 extension) and keeping the rules that predict real domains
without proposing a neighbour's. What each rule was worth is noted where it is
applied in :func:`candidate_domains_for_organization`.
"""

from typing import Optional

from django.utils.text import slugify

from core.models import Organization
from core.services.domainnames import normalize_domains
from core.services.domains import DOMAIN_EXTENSIONS_DEPARTEMENTS
from core.services.proconnect import domain_bucket


def _org_slug(name: str) -> Optional[str]:
    """Return the bare slug for a collectivité name, or ``None`` if empty.

    Slug rules follow :func:`django.utils.text.slugify` (accents stripped,
    lowercased, non-word runs collapsed to hyphens).
    """
    return slugify(name or "") or None


def slugify_org_domain(name: str) -> Optional[str]:
    """Return the candidate ``{slug}.fr`` domain derived from a collectivité name."""
    slug = _org_slug(name)
    return f"{slug}.fr" if slug else None


def _flatten_slug(slug: str) -> Optional[str]:
    """The slug with its hyphens removed, or ``None`` when it has none."""
    return slug.replace("-", "") if "-" in slug else None


def _saint_abbreviations(slug: str) -> set[str]:
    """``saint-``/``sainte-`` abbreviated to ``st-``/``ste-``, wherever they appear.

    Handles both the leading form ("saint-denis") and the inner one
    ("bazoches-et-saint-thibaut").
    """
    forms = set()
    if slug.startswith("saint-") or "-saint-" in slug:
        forms.add(slug.replace("saint-", "st-"))
    if slug.startswith("sainte-") or "-sainte-" in slug:
        forms.add(slug.replace("sainte-", "ste-"))
    return forms


def _slug_without_article(name: str) -> Optional[str]:
    """The slug of a name stripped of its leading article, or ``None`` if it has none.

    Works from the name rather than from the slug because :func:`slugify` glues an
    apostrophe article to the word that follows: "L'Abergement-de-Varey" becomes
    "labergement-de-varey", where the article is no longer separable.
    """
    stripped = (name or "").strip()
    lowered = stripped.lower()
    # Longest first, so "les " is not read as "le ". Both apostrophes occur in the
    # source data.
    for article in ("les ", "le ", "la ", "l'", "l’"):
        if lowered.startswith(article):
            return _org_slug(stripped[len(article) :])
    return None


def claimed_domains() -> dict[str, str]:
    """Map every domain a collectivité provably owns to that organization's id.

    "Provably" means DILA said so (``dpnt``) or a superuser validated it
    (``manual``). Requested and candidate domains are guesses and are left out.

    One query over every organization, so build it once per batch and pass it to
    :func:`candidate_domains_for_organization` — never call it in a loop.
    """
    owners: dict[str, str] = {}
    rows = Organization.objects.exclude(proconnect_domains={}).values_list(
        "pk", "proconnect_domains"
    )
    for pk, buckets in rows.iterator():
        if not isinstance(buckets, dict):
            continue
        for bucket in ("dpnt", "manual"):
            for domain in normalize_domains(buckets.get(bucket)):
                # First writer wins: two collectivités claiming the same domain is a
                # data problem of its own, and picking either one suppresses the
                # candidate for the other, which is what we want here.
                owners.setdefault(domain, pk)
    return owners


def candidate_domains_for_organization(
    organization: Organization, claimed: Optional[dict] = None
) -> list[str]:
    """Candidate domains for an org.

    - ``{slug}.<ext>`` for every RPNT-valid extension applicable to the org's
      département (always ``.fr``).
    - alternative spellings, added on top of those (never in place of them), and
      only when ``{slug}.fr`` is not already one of the org's DILA domains — a
      collectivité that already has its canonical domain needs no suggestions:

      - ``mairie-{slug}.fr``, ``ville-{slug}.fr``, ``{slug}{dept}.fr``;
      - the hyphenless spelling ``{flat}.fr``, plus ``mairie-``/``ville-``, the
        département number and the applicable regional extensions on it;
      - ``saint-``/``sainte-`` abbreviated to ``st-``/``ste-``, hyphenated and not;
      - a leading article dropped ("La Chapelle" -> "chapelle").

    ``claimed`` is a ``{domain: organization_id}`` map from :func:`claimed_domains`;
    when given, a domain another collectivité provably owns is never proposed.

    Only communes get candidate domains (EPCIs and other types are skipped).
    Returns a sorted list (empty if not a commune or the name yields no slug).
    """
    if organization.type != "commune":
        return []
    slug = _org_slug(organization.name)
    if not slug:
        return []
    # Département codes are compared against the uppercase table keys ("2A"/"2B"),
    # so normalize; the slug form below stays lowercase.
    dept = (organization.departement_code_insee or "").strip().upper()
    dpnt = set(domain_bucket(organization, "dpnt"))

    domains = {
        f"{slug}.{ext}"
        for ext, depts in DOMAIN_EXTENSIONS_DEPARTEMENTS.items()
        if depts is None or dept in depts
    }
    # Alternative forms, unless the plain {slug}.fr is already a DILA domain.
    if f"{slug}.fr" not in dpnt:
        domains.add(f"mairie-{slug}.fr")
        domains.add(f"ville-{slug}.fr")
        if dept:
            domains.add(f"{slug}{dept.lower()}.fr")

        # The hyphenless spelling: the single biggest miss of the hyphenated-only
        # generator, since a great many communes registered their name run together.
        flat = _flatten_slug(slug)
        if flat:
            domains.add(f"{flat}.fr")
            domains.add(f"mairie-{flat}.fr")
            domains.add(f"ville-{flat}.fr")
            if dept:
                domains.add(f"{flat}{dept.lower()}.fr")
            # Regional extensions on it too — nearly free, since each only applies
            # to the départements it serves.
            domains |= {
                f"{flat}.{ext}"
                for ext, depts in DOMAIN_EXTENSIONS_DEPARTEMENTS.items()
                if depts and dept in depts
            }

        # "saint-" is written "st-" about as often as not, hyphenated or run together.
        for abbreviated in _saint_abbreviations(slug):
            domains.add(f"{abbreviated}.fr")
            flat_abbreviated = _flatten_slug(abbreviated)
            if flat_abbreviated:
                domains.add(f"{flat_abbreviated}.fr")

        # A leading article is usually dropped when registering the domain. Only the
        # bare and hyphenless forms: measured against the DPNT dataset, the
        # "mairie-" one landed on a neighbour's domain twice as often as it was right.
        bare = _slug_without_article(organization.name)
        if bare:
            domains.add(f"{bare}.fr")
            flat_bare = _flatten_slug(bare)
            if flat_bare:
                domains.add(f"{flat_bare}.fr")

    # Never propose a domain that is already an authoritative DILA domain.
    domains -= dpnt
    # Nor one that provably belongs to another collectivité: a name rule lands on a
    # homonym's domain often enough that suggesting it would be a real mistake.
    if claimed:
        domains = {
            domain
            for domain in domains
            if claimed.get(domain) in (None, organization.pk)
        }
    return sorted(domains)
