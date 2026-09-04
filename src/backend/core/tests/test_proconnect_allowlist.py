"""
Tests for the ProConnect api-partenaires allowlist generation:

- domain-building logic in core/services/proconnect.py
- the proconnect_regen_candidate_domains command (fills the "candidates" bucket)
- the public allowlist API route (serves the YAML as text/plain, with comments)
"""

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest
import responses
import yaml
from rest_framework.test import APIClient

from core import factories
from core.services.domains_candidates import slugify_org_domain
from core.services.proconnect import (
    _effective_service_config,
    build_proconnect_allowlist,
    domain_bucket,
    domain_provenances,
    effective_config_memo,
    get_prevalidated_domains,
    known_domains,
    org_rpnt_valid_domains,
    proconnect_domains,
    render_proconnect_allowlist_yaml,
    routable_domains,
    update_proconnect_domains,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_allowlist_cache():
    """Keep the cached deployed allowlist from leaking between tests."""
    cache.clear()
    yield
    cache.clear()


def _proconnect_service(idp_id):
    return factories.ServiceFactory(type="proconnect", config={"idp_id": idp_id})


def _active_subscription(service, operator, domains, departement="01"):
    org = factories.OrganizationFactory(departement_code_insee=departement)
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org)
    factories.ServiceSubscriptionFactory(
        organization=org,
        service=service,
        operator=operator,
        metadata={"domains": domains},
        is_active=True,
    )
    return org


def _domains(entry):
    return [item["domain"] for item in entry["allowed_attached_email_domains"]]


# --- slugify -----------------------------------------------------------------


def test_slugify_org_domain_basic():
    """A hyphenated name maps to the matching .fr domain."""
    assert slugify_org_domain("Castellet-en-Luberon") == "castellet-en-luberon.fr"


def test_slugify_org_domain_strips_accents_and_spaces():
    """Accents are folded and spaces become hyphens."""
    assert (
        slugify_org_domain("Saint-Étienne du Rouvray") == "saint-etienne-du-rouvray.fr"
    )


def test_slugify_org_domain_empty():
    """A name with no slug yields no domain rather than a bare ".fr"."""
    assert slugify_org_domain("") is None
    assert slugify_org_domain("   ") is None


# --- RPNT-valid domains (used to compute the dpnt cache) ---------------------


def test_org_rpnt_valid_domains_website_only():
    """RPNT 1.1 alone validates the website's domain."""
    org = factories.OrganizationFactory(
        rpnt=["1.1"], site_internet="https://www.mairie-a.fr", adresse_messagerie=None
    )
    assert org_rpnt_valid_domains(org) == {"mairie-a.fr"}


def test_org_rpnt_valid_domains_email_needs_both_criteria():
    """The messaging domain counts only when both 2.1 and 2.2 are met."""
    org_ok = factories.OrganizationFactory(
        rpnt=["2.1", "2.2"], adresse_messagerie="contact@b.fr", site_internet=None
    )
    assert org_rpnt_valid_domains(org_ok) == {"b.fr"}

    org_partial = factories.OrganizationFactory(
        rpnt=["2.1"], adresse_messagerie="contact@c.fr", site_internet=None
    )
    assert org_rpnt_valid_domains(org_partial) == set()


# --- allowlist building ------------------------------------------------------


def test_build_allowlist_includes_routed_domains():
    """A subscription's domains land in its provider's entry, tagged "routed"."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    _active_subscription(service, operator, ["a.fr", "b.fr"])

    entries = build_proconnect_allowlist()
    assert len(entries) == 1
    assert entries[0]["uid"] == "idp-x"
    assert _domains(entries[0]) == ["a.fr", "b.fr"]
    assert all(
        i["source"] == "routed" for i in entries[0]["allowed_attached_email_domains"]
    )


def test_build_allowlist_covers_whole_departement_with_sources():
    """Scope is the operator's départements plus its managed orgs, each domain sourced."""
    # The operator's declared config["departements"] is the reference scope.
    operator = factories.OperatorFactory(config={"departements": ["42"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Org A in the covered département contributes via "dpnt".
    factories.OrganizationFactory(
        departement_code_insee="42", proconnect_domains={"dpnt": ["a.fr"]}
    )
    # Org B in the same département contributes via "candidates".
    factories.OrganizationFactory(
        departement_code_insee="42", proconnect_domains={"candidates": ["b.fr"]}
    )
    # Org C in another département -> excluded.
    factories.OrganizationFactory(
        departement_code_insee="99", proconnect_domains={"dpnt": ["c.fr"]}
    )

    # A managed org outside the declared départements is also in scope.
    managed = factories.OrganizationFactory(
        departement_code_insee="99", proconnect_domains={"dpnt": ["managed.fr"]}
    )
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=managed)

    entries = build_proconnect_allowlist()
    by_domain = {
        i["domain"]: i["source"] for i in entries[0]["allowed_attached_email_domains"]
    }
    assert by_domain.get("a.fr") == "DILA"
    assert by_domain.get("b.fr") == "candidates"
    assert by_domain.get("managed.fr") == "DILA"  # managed org, dept not declared
    assert "c.fr" not in by_domain


def test_build_allowlist_source_priority_prefers_dila():
    """A domain in several buckets is reported under the most authoritative one."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    factories.OrganizationFactory(
        departement_code_insee="01",
        proconnect_domains={
            "dpnt": ["x.fr"],
            "candidates": ["x.fr"],
            "manual": ["x.fr"],
        },
    )

    entries = build_proconnect_allowlist()
    by_domain = {
        i["domain"]: i["source"] for i in entries[0]["allowed_attached_email_domains"]
    }
    assert by_domain["x.fr"] == "DILA"


def test_build_allowlist_discard_excludes_candidates_but_not_dila():
    """A discarded candidates domain is excluded; a discarded DILA (dpnt) domain stays."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    factories.OrganizationFactory(
        departement_code_insee="01",
        proconnect_domains={
            "dpnt": ["dila.fr"],
            "candidates": ["extra.fr"],
            "discarded": ["dila.fr", "extra.fr"],
        },
    )

    entries = build_proconnect_allowlist()
    domains = {i["domain"] for i in entries[0]["allowed_attached_email_domains"]}
    assert "dila.fr" in domains  # DILA is authoritative, discard has no effect
    assert "extra.fr" not in domains  # candidates is discardable


def test_build_allowlist_discard_excludes_manual():
    """A discarded manual domain is excluded from the allowlist too."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    factories.OrganizationFactory(
        departement_code_insee="01",
        proconnect_domains={"manual": ["m.fr", "keep.fr"], "discarded": ["m.fr"]},
    )

    entries = build_proconnect_allowlist()
    domains = {i["domain"] for i in entries[0]["allowed_attached_email_domains"]}
    assert "keep.fr" in domains
    assert "m.fr" not in domains


def test_build_allowlist_keeps_routed_domain_even_when_discarded():
    """A currently-routed (live) domain stays in the allowlist even if discarded —
    routing is what the provider is actually using, stronger than any discard."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = _active_subscription(service, operator, ["live.fr"], departement="01")
    # A superuser discards the very domain that is currently routed/live.
    org.proconnect_domains = {"discarded": ["live.fr"]}
    org.save(update_fields=["proconnect_domains"])

    entries = build_proconnect_allowlist()
    domains = {
        item["domain"]
        for entry in entries
        for item in entry["allowed_attached_email_domains"]
    }
    assert "live.fr" in domains


def test_build_allowlist_routed_domain_does_not_leak_across_idps():
    """A domain routed to idp-a must not appear in idp-b's allowlist, even when the
    same operator manages the org for both providers."""
    operator = factories.OperatorFactory(config={"departements": []})
    svc_a = _proconnect_service("idp-a")
    svc_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=operator, service=svc_a)
    factories.OperatorServiceConfigFactory(operator=operator, service=svc_b)
    org = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org)
    # org routes onlya.fr to idp-a only.
    factories.ServiceSubscriptionFactory(
        organization=org,
        service=svc_a,
        operator=operator,
        metadata={"domains": ["onlya.fr"]},
        is_active=True,
    )

    by_uid = {
        entry["uid"]: {
            item["domain"] for item in entry["allowed_attached_email_domains"]
        }
        for entry in build_proconnect_allowlist()
    }
    assert "onlya.fr" in by_uid.get("idp-a", set())
    assert "onlya.fr" not in by_uid.get("idp-b", set())


def test_domain_bucket_rejects_non_hostname_values():
    """Junk (spaces, newlines, YAML metachars) is dropped from buckets so it can
    never be injected into the allowlist YAML."""
    org = factories.OrganizationFactory(
        proconnect_domains={
            "manual": ["ok.fr", "UP.FR", "bad domain.fr", "evil.fr\n      - x.fr"]
        }
    )
    assert domain_bucket(org, "manual") == ["ok.fr", "up.fr"]


def test_update_proconnect_domains_promotes_domain_to_dpnt_only():
    """A domain entering dpnt is stripped from manual/requested/candidates — the
    end state after the dpnt import declares it on service-public.gouv.fr."""
    org = factories.OrganizationFactory(
        proconnect_domains={
            "manual": ["x.fr", "keep-manual.fr"],
            "requested": ["x.fr"],
            "candidates": ["x.fr", "keep-cand.fr"],
        }
    )
    update_proconnect_domains(org, dpnt=["x.fr"])

    buckets = proconnect_domains(org)
    assert buckets["dpnt"] == ["x.fr"]
    assert buckets["manual"] == ["keep-manual.fr"]
    assert buckets["requested"] == []
    assert buckets["candidates"] == ["keep-cand.fr"]


def test_build_allowlist_uses_effective_idp_override():
    """The allowlist is keyed by the *effective* idp (operator override wins),
    matching what the push path (subscription_idp_id) actually targets."""
    operator = factories.OperatorFactory(config={"departements": ["45"]})
    service = _proconnect_service("base-idp")
    factories.OperatorServiceConfigFactory(
        operator=operator, service=service, config_override={"idp_id": "override-idp"}
    )
    factories.OrganizationFactory(
        departement_code_insee="45", proconnect_domains={"manual": ["x.fr"]}
    )

    entries = build_proconnect_allowlist()
    uids = {entry["uid"] for entry in entries}
    assert "override-idp" in uids
    assert "base-idp" not in uids
    entry = next(e for e in entries if e["uid"] == "override-idp")
    assert "x.fr" in {
        item["domain"] for item in entry["allowed_attached_email_domains"]
    }


def test_routable_domains_keeps_dila_and_drops_discarded():
    """A discard hides a candidate or a manual domain, never a DILA one."""
    org = factories.OrganizationFactory(
        proconnect_domains={
            "manual": ["m.fr"],
            "candidates": ["c.fr"],
            "dpnt": ["d.fr"],
            # A pending ask is not routable, whatever else happens.
            "requested": ["r.fr"],
            # d.fr is DILA -> its discard is ignored; c.fr is genuinely discarded.
            "discarded": ["c.fr", "d.fr"],
        }
    )
    assert routable_domains(org) == ["d.fr", "m.fr"]
    assert domain_provenances(org) == {"d.fr": "dpnt", "m.fr": "manual"}
    # Everything we display, routable or not.
    assert known_domains(org) == {"m.fr", "c.fr", "d.fr", "r.fr"}


def test_routable_domains_keeps_a_discarded_domain_that_is_live():
    """Discarding a routed domain must not cut off the users behind it."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    org = _active_subscription(service, operator, ["live.fr"])
    update_proconnect_domains(org, manual=["live.fr"], discarded=["live.fr"])

    assert routable_domains(org) == ["live.fr"]
    # It is still live, so that is what it is reported as.
    assert domain_provenances(org, "idp-x") == {"live.fr": "manual"}


# --- YAML rendering ----------------------------------------------------------


def test_render_yaml_with_comments():
    """Each domain carries its source (and Service-Public URL) as a trailing comment."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [
                {
                    "domain": "a.fr",
                    "source": "DILA",
                    "service_public_url": "https://sp.fr/a",
                },
                {"domain": "b.fr", "source": "candidates", "service_public_url": None},
            ],
        },
        {"uid": "y", "allowed_attached_email_domains": []},
    ]
    expected = (
        "oidc_providers:\n"
        '  - uid: "x"\n'
        "    allowed_attached_email_domains:\n"
        "      - a.fr  # Source: DILA | https://sp.fr/a\n"
        "      - b.fr  # Source: candidates\n"
        '  - uid: "y"\n'
        "    allowed_attached_email_domains: []\n"
    )
    assert render_proconnect_allowlist_yaml(entries) == expected


def test_render_yaml_escapes_uid():
    """A uid with a quote/newline must not break out of its YAML scalar."""
    entries = [{"uid": 'a"b\nc', "allowed_attached_email_domains": []}]

    rendered = render_proconnect_allowlist_yaml(entries)

    assert rendered == (
        'oidc_providers:\n  - uid: "a\\"b\\nc"\n'
        "    allowed_attached_email_domains: []\n"
    )
    # And it still parses back to the original uid.
    assert yaml.safe_load(rendered)["oidc_providers"][0]["uid"] == 'a"b\nc'


def test_render_yaml_comment_cannot_inject_a_line():
    """A newline in the imported Service-Public URL must not add an entry."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [
                {
                    "domain": "a.fr",
                    "source": "DILA",
                    "service_public_url": "https://sp.fr/a\n      - evil.fr  # Source: DILA",
                }
            ],
        }
    ]

    rendered = render_proconnect_allowlist_yaml(entries)

    assert "evil.fr" in rendered  # still visible, but only inside the comment
    parsed = yaml.safe_load(rendered)["oidc_providers"][0]
    assert parsed["allowed_attached_email_domains"] == ["a.fr"]


# --- proconnect_regen_candidate_domains command --------------------------------------


def test_suggest_domains_command_populates_candidates():
    """The command writes the generator's full output to the candidates bucket."""
    org = factories.OrganizationFactory(name="Ville A", departement_code_insee="45")
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert set(domain_bucket(org, "candidates")) == {
        "ville-a.fr",
        "ville-a45.fr",
        "mairie-ville-a.fr",
        "ville-ville-a.fr",
        # The hyphenless spelling and its prefixed/département forms.
        "villea.fr",
        "mairie-villea.fr",
        "ville-villea.fr",
        "villea45.fr",
    }


def test_suggest_domains_command_adds_fr_variants():
    """When {slug}.fr is not the org's DILA domain, add mairie-/ville-/{slug}{dept}."""
    org = factories.OrganizationFactory(name="Aiglun", departement_code_insee="06")
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert set(domain_bucket(org, "candidates")) == {
        "aiglun.fr",
        "aiglun06.fr",
        "mairie-aiglun.fr",
        "ville-aiglun.fr",
    }


def test_suggest_domains_command_no_candidate_when_dila_has_slug():
    """When {slug}.fr is already the org's DILA domain: no .fr variants, and
    {slug}.fr itself is not re-proposed as a candidate (it is already authoritative)."""
    org = factories.OrganizationFactory(
        name="Aiglun",
        departement_code_insee="06",
        proconnect_domains={"dpnt": ["aiglun.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert domain_bucket(org, "candidates") == []


def test_suggest_domains_command_adds_bzh_for_brittany():
    """Breton départements (22/29/35/44/56) also get a {slug}.bzh suggestion."""
    org = factories.OrganizationFactory(
        name="Brest",
        departement_code_insee="29",
        # brest.fr is the DILA domain -> dropped + no .fr variants; .bzh still stands.
        proconnect_domains={"dpnt": ["brest.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert domain_bucket(org, "candidates") == ["brest.bzh"]


def test_suggest_domains_command_adds_regional_and_om_extensions():
    """Réunion (974) gets .re, Corsica (2A) gets .corsica, in addition to .fr."""
    # {slug}.fr is each org's DILA domain -> dropped + no .fr variants; the
    # regional/OM extension still stands.
    reunion = factories.OrganizationFactory(
        name="Saint-Denis",
        departement_code_insee="974",
        proconnect_domains={"dpnt": ["saint-denis.fr"]},
    )
    corsica = factories.OrganizationFactory(
        name="Ajaccio",
        departement_code_insee="2A",
        proconnect_domains={"dpnt": ["ajaccio.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    reunion.refresh_from_db()
    corsica.refresh_from_db()
    assert domain_bucket(reunion, "candidates") == ["saint-denis.re"]
    assert domain_bucket(corsica, "candidates") == ["ajaccio.corsica"]


def test_suggest_domains_command_only_communes():
    """EPCIs (and other non-commune types) get no candidates suggestion."""
    epci = factories.OrganizationFactory(
        name="CC Test", type="epci", departement_code_insee="45"
    )
    call_command("proconnect_regen_candidate_domains")
    epci.refresh_from_db()
    assert domain_bucket(epci, "candidates") == []


def test_suggest_domains_command_preserves_other_buckets():
    """Regenerating candidates leaves the other buckets alone, and is idempotent."""
    org = factories.OrganizationFactory(
        name="Aiglun",
        departement_code_insee="06",
        proconnect_domains={"manual": ["manual.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    expected = {"aiglun.fr", "aiglun06.fr", "mairie-aiglun.fr", "ville-aiglun.fr"}
    assert set(domain_bucket(org, "candidates")) == expected
    assert domain_bucket(org, "manual") == ["manual.fr"]

    # Idempotent.
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert set(domain_bucket(org, "candidates")) == expected
    assert domain_bucket(org, "manual") == ["manual.fr"]


def test_suggest_domains_command_skips_when_rpnt_complete():
    """No candidates suggestion for an org that already satisfies the full RPNT set."""
    org = factories.OrganizationFactory(
        name="Ville A",
        departement_code_insee="45",
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert domain_bucket(org, "candidates") == []


def test_suggest_domains_command_skips_discarded():
    """A discarded slug is never re-suggested into candidates (per TLD)."""
    org = factories.OrganizationFactory(
        name="Brest",
        departement_code_insee="29",
        # dpnt has brest.fr -> no .fr variants; brest.fr also discarded.
        proconnect_domains={"discarded": ["brest.fr"], "dpnt": ["brest.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    # .fr discarded, but the Breton .bzh is still suggested.
    assert domain_bucket(org, "candidates") == ["brest.bzh"]
    assert domain_bucket(org, "discarded") == ["brest.fr"]


def test_suggest_domains_command_dry_run_does_not_write():
    """--dry-run prints what it would add without touching the database."""
    org = factories.OrganizationFactory(name="Ville A", departement_code_insee="45")
    out = StringIO()
    call_command("proconnect_regen_candidate_domains", "--dry-run", stdout=out)
    org.refresh_from_db()
    assert domain_bucket(org, "candidates") == []
    assert "ville-a.fr" in out.getvalue()


def test_suggest_domains_command_filters_by_operator():
    """--operator restricts the regeneration to that operator's organizations."""
    op1 = factories.OperatorFactory()
    op2 = factories.OperatorFactory()
    org1 = factories.OrganizationFactory(name="Ville One", departement_code_insee="45")
    org2 = factories.OrganizationFactory(name="Ville Two", departement_code_insee="45")
    factories.OperatorOrganizationRoleFactory(operator=op1, organization=org1)
    factories.OperatorOrganizationRoleFactory(operator=op2, organization=org2)

    call_command("proconnect_regen_candidate_domains", "--operator", str(op1.id))

    org1.refresh_from_db()
    org2.refresh_from_db()
    assert set(domain_bucket(org1, "candidates")) == {
        "ville-one.fr",
        "ville-one45.fr",
        "mairie-ville-one.fr",
        "ville-ville-one.fr",
        "villeone.fr",
        "mairie-villeone.fr",
        "ville-villeone.fr",
        "villeone45.fr",
    }
    assert domain_bucket(org2, "candidates") == []


# --- allowlist API route -----------------------------------------------------

ALLOWLIST_KEY = "allowlist-key-123"
allowlist_key_settings = override_settings(
    PROCONNECT_ALLOWLIST_VIEW_API_KEY=ALLOWLIST_KEY
)


def _get_allowlist(**kwargs):
    """GET the allowlist route bearing the configured key."""
    return APIClient().get(
        reverse("api-proconnect-allowlist"),
        HTTP_AUTHORIZATION=f"Bearer {ALLOWLIST_KEY}",
        **kwargs,
    )


@allowlist_key_settings
def test_allowlist_api_route_serves_yaml_text_plain():
    """The route renders the built allowlist as text/plain YAML with source comments."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = _active_subscription(service, operator, ["sub.fr"], departement="42")
    org.service_public_url = "https://service-public.fr/org"
    org.proconnect_domains = {"dpnt": ["dila.fr"], "manual": ["manual.fr"]}
    org.save()

    response = _get_allowlist()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert body.startswith("oidc_providers:")
    assert 'uid: "idp-x"' in body
    assert "- sub.fr" in body  # routed
    assert "- dila.fr" in body  # dpnt (DILA) cache
    assert "- manual.fr" in body  # manual
    assert "# Source: DILA | https://service-public.fr/org" in body


def test_allowlist_api_route_is_closed_without_a_key():
    """An unset PROCONNECT_ALLOWLIST_VIEW_API_KEY closes the route, never opens it."""
    _proconnect_service("idp-x")
    assert _get_allowlist().status_code == 403
    assert APIClient().get(reverse("api-proconnect-allowlist")).status_code == 403


@allowlist_key_settings
def test_allowlist_api_route_rejects_a_missing_authorization():
    """With a key configured, an unauthenticated call is refused."""
    _proconnect_service("idp-x")
    response = APIClient().get(reverse("api-proconnect-allowlist"))
    assert response.status_code == 403
    assert "detail" not in response.content.decode()  # rendered as plain text


@allowlist_key_settings
def test_allowlist_api_route_rejects_a_wrong_bearer_token():
    """A well-formed bearer token that isn't the configured key is refused."""
    _proconnect_service("idp-x")
    response = APIClient().get(
        reverse("api-proconnect-allowlist"), HTTP_AUTHORIZATION="Bearer wrong"
    )
    assert response.status_code == 403


@allowlist_key_settings
def test_allowlist_api_route_rejects_the_key_without_the_bearer_prefix():
    """The key alone is not accepted: the "Bearer " scheme is required."""
    _proconnect_service("idp-x")
    response = APIClient().get(
        reverse("api-proconnect-allowlist"), HTTP_AUTHORIZATION=ALLOWLIST_KEY
    )
    assert response.status_code == 403


@allowlist_key_settings
def test_allowlist_api_route_accepts_the_matching_bearer_token():
    """The configured key sent as a bearer token gets the YAML."""
    _proconnect_service("idp-x")
    response = _get_allowlist()
    assert response.status_code == 200
    assert response.content.decode().startswith("oidc_providers:")


@allowlist_key_settings
def test_allowlist_api_route_reflects_a_change_immediately():
    """Built per request: no cache to serve a stale allowlist to the next caller."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    assert 'uid: "idp-x"' in _get_allowlist().content.decode()

    late = _proconnect_service("idp-late")
    factories.OperatorServiceConfigFactory(operator=operator, service=late)
    assert 'uid: "idp-late"' in _get_allowlist().content.decode()


def test_build_allowlist_resolves_each_service_config_once():
    """The effective config is memoized per build, not re-queried per subscription."""
    operator = factories.OperatorFactory(config={"departements": ["42"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    for _ in range(5):
        _active_subscription(service, operator, ["a.fr"], departement="42")

    with CaptureQueriesContext(connection) as ctx:
        build_proconnect_allowlist()

    config_queries = [
        q
        for q in ctx.captured_queries
        if "deploycenter_operator_service_config" in q["sql"]
    ]
    # One (service, operator) pair -> one lookup, however many subscriptions.
    assert len(config_queries) <= 2, config_queries


def test_memo_does_not_outlive_its_block():
    """A config resolved inside the memo is not reused by a later, separate call."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    config = factories.OperatorServiceConfigFactory(operator=operator, service=service)

    with effective_config_memo():
        assert _effective_service_config(service, operator)["idp_id"] == "idp-x"

    config.config_override = {"idp_id": "idp-changed"}
    config.save()
    # Outside the block the next read hits the DB again.
    assert _effective_service_config(service, operator)["idp_id"] == "idp-changed"


# --- proconnect_fetch_prevalidated command -----------------------------------


@responses.activate
def test_fetch_prevalidated_caches_per_idp_allowlist():
    """The command caches each provider's allowed domains (empty set stays defined)."""
    yaml_text = (
        "oidc_providers:\n"
        '  - uid: "idp-x"\n'
        "    allowed_attached_email_domains:\n"
        "      - b.fr\n"
        "      - a.fr\n"  # stored normalized + sorted
        '  - uid: "idp-y"\n'
        "    allowed_attached_email_domains: []\n"
    )
    responses.add(
        responses.GET, "https://allowlist.test/x.yaml", body=yaml_text, status=200
    )

    out = StringIO()
    call_command(
        "proconnect_fetch_prevalidated",
        "--url",
        "https://allowlist.test/x.yaml",
        stdout=out,
    )

    assert get_prevalidated_domains("idp-x") == ["a.fr", "b.fr"]
    assert get_prevalidated_domains("idp-y") == []  # empty but DEFINED
    assert get_prevalidated_domains("idp-z") is None  # never seen → unknown


@responses.activate
def test_fetch_prevalidated_raises_on_fetch_error():
    """An HTTP error fails the command instead of caching an empty allowlist."""
    responses.add(responses.GET, "https://allowlist.test/x.yaml", status=500)
    with pytest.raises(CommandError):
        call_command(
            "proconnect_fetch_prevalidated", "--url", "https://allowlist.test/x.yaml"
        )


@responses.activate
def test_fetch_prevalidated_raises_when_the_document_is_not_a_mapping():
    """A YAML list (or scalar) fails the command rather than raising AttributeError."""
    responses.add(
        responses.GET, "https://allowlist.test/x.yaml", body="- a\n- b\n", status=200
    )
    with pytest.raises(CommandError, match="expected a mapping"):
        call_command(
            "proconnect_fetch_prevalidated", "--url", "https://allowlist.test/x.yaml"
        )


@responses.activate
def test_fetch_prevalidated_does_not_leak_url_credentials():
    """A --url with userinfo is redacted before it reaches the error message."""
    url = "https://user:s3cr3t@allowlist.test/x.yaml"
    responses.add(responses.GET, url, status=500)
    with pytest.raises(CommandError) as excinfo:
        call_command("proconnect_fetch_prevalidated", "--url", url)
    assert "s3cr3t" not in str(excinfo.value)
    assert "https://***@allowlist.test/x.yaml" in str(excinfo.value)


def test_fetch_prevalidated_refuses_credentials_over_plaintext():
    """Userinfo becomes a Basic auth header; not over http."""
    with pytest.raises(CommandError, match="Refusing to send credentials"):
        call_command(
            "proconnect_fetch_prevalidated",
            "--url",
            "http://user:s3cr3t@allowlist.test/x.yaml",
        )


@responses.activate
def test_fetch_prevalidated_allows_a_plaintext_url_without_credentials():
    """The scheme check is about the credentials, not the scheme alone."""
    url = "http://allowlist.test/x.yaml"
    responses.add(
        responses.GET,
        url,
        body='oidc_providers:\n  - uid: "idp-x"\n    allowed_attached_email_domains: []\n',
        status=200,
    )
    call_command("proconnect_fetch_prevalidated", "--url", url, stdout=StringIO())
    assert get_prevalidated_domains("idp-x") == []
