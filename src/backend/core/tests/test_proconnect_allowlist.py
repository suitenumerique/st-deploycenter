"""
Tests for the ProConnect api-partenaires allowlist generation:

- domain-building logic in core/services/proconnect.py
- the proconnect_regen_candidate_domains command (fills the "candidates" bucket)
- the public allowlist API route (serves the YAML as text/plain)
"""
# pylint: disable=too-many-lines

import io
from io import StringIO
from unittest import mock

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
from core.models import OperatorServiceConfig
from core.services.domains_candidates import slugify_org_domain
from core.services.proconnect import (
    AllowlistFormatError,
    build_proconnect_allowlist,
    domain_bucket,
    domain_provenances,
    get_prevalidated_domains,
    iter_allowlist_providers,
    iter_proconnect_allowlist_yaml,
    known_domains,
    org_rpnt_valid_domains,
    proconnect_domains,
    render_proconnect_allowlist_yaml,
    routable_domains,
    store_prevalidated_domains,
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


FICHE = (
    "https://lannuaire.service-public.gouv.fr/bretagne/morbihan/"
    "abab3da3-4cd6-42f1-ac88-9fa3f1bc4154"
)
SIRET = "21560123400017"
FICHE_OTHER = (
    "https://lannuaire.service-public.gouv.fr/auvergne-rhone-alpes/ain/"
    "0b3f1a52-7c1e-4d8b-9a46-2e5d6f7a8b90"
)
SIRET_OTHER = "21010123400019"


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
        departement_code_insee="42",
        service_public_url=FICHE,
        siret=SIRET,
        proconnect_domains={"dpnt": ["a.fr"]},
    )
    # Org B in the same département contributes via "candidates".
    factories.OrganizationFactory(
        departement_code_insee="42",
        service_public_url=FICHE,
        siret="21350001000011",
        proconnect_domains={"candidates": ["b.fr"]},
    )
    # Org C in another département -> excluded.
    factories.OrganizationFactory(
        departement_code_insee="99", proconnect_domains={"dpnt": ["c.fr"]}
    )

    # A managed org outside the declared départements is also in scope.
    managed = factories.OrganizationFactory(
        departement_code_insee="99",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["managed.fr"]},
    )
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=managed)

    entries = build_proconnect_allowlist()
    by_domain = {i["domain"]: i for i in entries[0]["allowed_attached_email_domains"]}
    assert by_domain["a.fr"]["source"] == "dila"
    assert by_domain["a.fr"]["fiche"] == FICHE
    assert by_domain["a.fr"]["siret"] == SIRET
    # A candidate is not live: "candidate", with the fiche and SIRET of its commune.
    assert by_domain["b.fr"]["source"] == "candidate"
    assert by_domain["b.fr"]["fiche"] == FICHE
    assert by_domain["b.fr"]["siret"] == "21350001000011"
    # managed org, dept not declared
    assert by_domain["managed.fr"]["source"] == "dila"
    assert "c.fr" not in by_domain


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://www.example.com/page",
        "https://lannuaire.service-public.gouv.fr/bretagne/morbihan/not-a-uuid",
        "http://lannuaire.service-public.gouv.fr/bretagne/morbihan/"
        "abab3da3-4cd6-42f1-ac88-9fa3f1bc4154",
        FICHE + "\n      - evil.fr",
        FICHE.replace("morbihan", "a b"),
        FICHE.replace("morbihan", 'a"b'),
    ],
)
def test_build_allowlist_dila_domain_without_a_valid_fiche_is_a_candidate(url):
    """api-partenaires wants a fiche on every "dila" row: without a usable one
    the DILA domain is not "dila" (here not live either, so "candidate")."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = factories.OrganizationFactory(
        departement_code_insee="01", proconnect_domains={"dpnt": ["x.fr"]}
    )
    # The DILA import writes the URL without full_clean(): do the same.
    type(org).objects.filter(pk=org.pk).update(service_public_url=url)

    (item,) = build_proconnect_allowlist()[0]["allowed_attached_email_domains"]

    assert item["source"] == "candidate"
    assert item["fiche"] is None


def test_build_allowlist_routed_means_live_only():
    """A live domain is `routed` whatever bucket also holds it; the others are
    `manual` or `candidate` after their bucket."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = _active_subscription(
        service, operator, ["live.fr", "live-cand.fr", "live-manual.fr"]
    )
    org.proconnect_domains = {
        "candidates": ["live-cand.fr", "cand.fr"],
        "manual": ["manual.fr", "live-manual.fr"],
    }
    org.save()

    by_domain = {
        i["domain"]: i["source"]
        for i in build_proconnect_allowlist()[0]["allowed_attached_email_domains"]
    }

    assert by_domain == {
        "live.fr": "routed",
        "live-cand.fr": "routed",  # live wins over its candidates bucket
        "live-manual.fr": "routed",  # and over its manual bucket
        "cand.fr": "candidate",
        "manual.fr": "manual",
    }


@pytest.mark.parametrize(
    "org_type,with_fiche",
    [("commune", True), ("epci", True), ("departement", True), ("region", True)]
    + [("ccas", False), ("syndicat", False)],
)
def test_build_allowlist_fiche_follows_the_organization_type(org_type, with_fiche):
    """A non-DILA row carries its fiche when the organization is a commune, an
    EPCI, a département or a région; its SIRET is there whatever the type."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    factories.OrganizationFactory(
        departement_code_insee="01",
        type=org_type,
        service_public_url=FICHE,
        siret=SIRET,
        proconnect_domains={"candidates": ["x.fr"]},
    )

    (item,) = build_proconnect_allowlist()[0]["allowed_attached_email_domains"]

    assert item["source"] == "candidate"
    assert item["fiche"] == (FICHE if with_fiche else None)
    assert item["siret"] == SIRET


@pytest.mark.parametrize(
    "siret", [None, "", "123", "1234567890123A", "２１５６０１２３４０００１７"]
)
def test_build_allowlist_dila_domain_without_a_valid_siret_has_none(siret):
    """The SIRET is optional: a missing or malformed one is left out, and the
    domain stays "dila" (the fiche is what api-partenaires requires)."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = factories.OrganizationFactory(
        departement_code_insee="01",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["x.fr"]},
    )
    # Imported data is not always cleaned: write it as the import does.
    type(org).objects.filter(pk=org.pk).update(siret=siret)

    (item,) = build_proconnect_allowlist()[0]["allowed_attached_email_domains"]

    assert item["source"] == "dila"
    assert item["fiche"] == FICHE
    assert item["siret"] is None


def test_build_allowlist_source_priority_prefers_dila():
    """A domain in several buckets is reported under the most authoritative one."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    factories.OrganizationFactory(
        departement_code_insee="01",
        service_public_url=FICHE,
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
    assert by_domain["x.fr"] == "dila"


def test_build_allowlist_live_dila_domain_is_routed():
    """A live domain is "routed" even when DILA declares it: api-partenaires checks
    every "dila" row against DILA and refuses the ones that fail, but takes
    "routed" as is. A DILA domain that is not live stays "dila"."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = factories.OrganizationFactory(
        departement_code_insee="01",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["live.fr", "idle.fr"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=org,
        service=service,
        operator=operator,
        metadata={"domains": ["live.fr"]},
        is_active=True,
    )

    assert _sources_by_uid() == {"idp-x": {"live.fr": "routed", "idle.fr": "dila"}}


def _homonyms(**overrides):
    """Two communes named Xyz in one provider, ordered by primary key, each with
    its own fiche and SIRET."""
    operator = factories.OperatorFactory(config={"departements": ["01"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    orgs = [
        factories.OrganizationFactory(
            name="Xyz",
            type="commune",
            departement_code_insee="01",
            service_public_url=fiche,
            siret=siret,
            **overrides,
        )
        for fiche, siret in ((FICHE, SIRET), (FICHE_OTHER, SIRET_OTHER))
    ]
    first, second = sorted(orgs, key=lambda org: org.pk)
    return operator, service, first, second


def _xyz_row():
    entry = build_proconnect_allowlist()[0]
    (item,) = [
        i for i in entry["allowed_attached_email_domains"] if i["domain"] == "xyz.fr"
    ]
    return item


def test_build_allowlist_homonym_candidates_go_to_the_first_organization():
    """Two homonyms both guess xyz.fr in one provider: one row, always the lowest
    primary key's fiche and SIRET, never whichever the database returned first."""
    _, _, first, _ = _homonyms(proconnect_domains={"candidates": ["xyz.fr"]})

    item = _xyz_row()

    assert item["source"] == "candidate"
    assert item["fiche"] == first.service_public_url
    assert item["siret"] == first.siret


@pytest.mark.parametrize("also_a_candidate", [True, False])
def test_build_allowlist_routing_homonym_owns_the_row(also_a_candidate):
    """Once one of two homonyms routes xyz.fr, the row carries its fiche and SIRET,
    even when it is not the first organization walked."""
    operator, service, _, second = _homonyms(
        proconnect_domains={"candidates": ["xyz.fr"]}
    )
    if not also_a_candidate:
        second.proconnect_domains = {}
        second.save()
    factories.ServiceSubscriptionFactory(
        organization=second,
        service=service,
        operator=operator,
        metadata={"domains": ["xyz.fr"]},
        is_active=True,
    )

    item = _xyz_row()

    assert item["source"] == "routed"
    assert item["fiche"] == second.service_public_url
    assert item["siret"] == second.siret


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


def _sources_by_uid():
    return {
        entry["uid"]: {
            item["domain"]: item["source"]
            for item in entry["allowed_attached_email_domains"]
        }
        for entry in build_proconnect_allowlist()
    }


def test_build_allowlist_domain_live_on_one_idp_is_not_proposed_on_another():
    """A commune routed to xyz.bzh on idp-a, with xyz.bzh also in its manual bucket,
    gets the `routed` row on idp-a only: idp-b would reject it as already taken."""
    operator = factories.OperatorFactory(config={"departements": ["22"]})
    svc_a = _proconnect_service("idp-a")
    svc_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=operator, service=svc_a)
    factories.OperatorServiceConfigFactory(operator=operator, service=svc_b)
    org = factories.OrganizationFactory(
        departement_code_insee="22",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["xyz.fr"], "manual": ["xyz.bzh"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=org,
        service=svc_a,
        operator=operator,
        metadata={"domains": ["xyz.bzh"]},
        is_active=True,
    )

    assert _sources_by_uid() == {
        "idp-a": {"xyz.fr": "dila", "xyz.bzh": "routed"},
        "idp-b": {"xyz.fr": "dila"},
    }


def test_build_allowlist_candidate_live_for_another_org_on_another_idp_is_dropped():
    """A candidate guess that another collectivité already routes elsewhere is not
    proposed, wherever that collectivité sits."""
    op_a = factories.OperatorFactory(config={"departements": ["01"]})
    op_b = factories.OperatorFactory(config={"departements": ["42"]})
    svc_a = _proconnect_service("idp-a")
    svc_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=op_a, service=svc_a)
    factories.OperatorServiceConfigFactory(operator=op_b, service=svc_b)
    factories.ServiceSubscriptionFactory(
        organization=factories.OrganizationFactory(departement_code_insee="01"),
        service=svc_a,
        operator=op_a,
        metadata={"domains": ["taken.fr"]},
        is_active=True,
    )
    factories.OrganizationFactory(
        departement_code_insee="42",
        proconnect_domains={"candidates": ["taken.fr", "free.fr"]},
    )

    assert _sources_by_uid() == {
        "idp-a": {"taken.fr": "routed"},
        "idp-b": {"free.fr": "candidate"},
    }


def _two_providers_one_operator_dila_domain(second_declarer):
    """An EPCI routing ``shared.bzh`` on idp-a, DILA domain of its own, with idp-b
    in the same scope; optionally a commune declaring it at DILA too."""
    operator = factories.OperatorFactory(config={"departements": ["56"]})
    svc_a = _proconnect_service("idp-a")
    svc_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=operator, service=svc_a)
    factories.OperatorServiceConfigFactory(operator=operator, service=svc_b)
    epci = factories.OrganizationFactory(
        departement_code_insee="56",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["shared.bzh"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=epci,
        service=svc_a,
        operator=operator,
        metadata={"domains": ["shared.bzh"]},
        is_active=True,
    )
    if second_declarer:
        factories.OrganizationFactory(
            departement_code_insee="56",
            service_public_url=FICHE_OTHER,
            proconnect_domains={"dpnt": ["shared.bzh"]},
        )


def test_build_allowlist_dila_domain_routed_elsewhere_and_shared_is_dropped():
    """The EPCI routes shared.bzh on idp-a and a commune declares it at DILA too:
    idp-b must not get a second row for it, `dila` or otherwise."""
    _two_providers_one_operator_dila_domain(second_declarer=True)

    assert _sources_by_uid() == {"idp-a": {"shared.bzh": "routed"}, "idp-b": {}}


def test_build_allowlist_dila_domain_routed_elsewhere_alone_is_kept():
    """Declared by a single collectivité, a DILA domain stays on every provider the
    collectivité is in scope of, even where it is not the one routing it."""
    _two_providers_one_operator_dila_domain(second_declarer=False)

    assert _sources_by_uid() == {
        "idp-a": {"shared.bzh": "routed"},
        "idp-b": {"shared.bzh": "dila"},
    }


def test_build_allowlist_candidate_is_dropped_when_another_org_has_it_at_dila():
    """crozet.fr is DILA for the commune of the Ain; the Loire's Le Crozet must not
    get it as a candidate on its own provider, which the Ain's org is not scoped to."""
    op_a = factories.OperatorFactory(config={"departements": ["01"]})
    op_b = factories.OperatorFactory(config={"departements": ["42"]})
    svc_a = _proconnect_service("idp-a")
    svc_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=op_a, service=svc_a)
    factories.OperatorServiceConfigFactory(operator=op_b, service=svc_b)
    factories.OrganizationFactory(
        departement_code_insee="01",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["crozet.fr"]},
    )
    factories.OrganizationFactory(
        departement_code_insee="42",
        proconnect_domains={"candidates": ["crozet.fr", "le-crozet.fr"]},
    )

    assert _sources_by_uid() == {
        "idp-a": {"crozet.fr": "dila"},
        "idp-b": {"le-crozet.fr": "candidate"},
    }


def test_build_allowlist_manual_domain_stays_when_another_org_has_it_at_dila():
    """Unlike a guess, a domain a superuser added by hand is kept."""
    op_a = factories.OperatorFactory(config={"departements": ["01"]})
    op_b = factories.OperatorFactory(config={"departements": ["42"]})
    svc_a = _proconnect_service("idp-a")
    svc_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=op_a, service=svc_a)
    factories.OperatorServiceConfigFactory(operator=op_b, service=svc_b)
    factories.OrganizationFactory(
        departement_code_insee="01",
        service_public_url=FICHE,
        proconnect_domains={"dpnt": ["shared.fr"]},
    )
    factories.OrganizationFactory(
        departement_code_insee="42",
        proconnect_domains={"manual": ["shared.fr"]},
    )

    assert _sources_by_uid()["idp-b"] == {"shared.fr": "manual"}


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


def test_build_allowlist_ignores_an_operator_idp_override():
    """The allowlist is keyed by the service's idp, matching what the push path
    (subscription_idp_id) targets; an operator override (legacy data) is inert."""
    operator = factories.OperatorFactory(config={"departements": ["45"]})
    service = _proconnect_service("base-idp")
    config = factories.OperatorServiceConfigFactory(operator=operator, service=service)
    # Written around save(), which refuses the key.
    OperatorServiceConfig.objects.filter(pk=config.pk).update(
        config_override={"idp_id": "override-idp"}
    )
    factories.OrganizationFactory(
        departement_code_insee="45", proconnect_domains={"manual": ["x.fr"]}
    )

    entries = build_proconnect_allowlist()
    uids = {entry["uid"] for entry in entries}
    assert "base-idp" in uids
    assert "override-idp" not in uids
    entry = next(e for e in entries if e["uid"] == "base-idp")
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


def test_render_yaml_matches_the_api_partenaires_format():
    """Fiche and SIRET come out in this order, each only when the row has it."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [
                {"domain": "a.fr", "source": "dila", "fiche": FICHE, "siret": SIRET},
                {"domain": "c.fr", "source": "dila", "fiche": FICHE, "siret": None},
                {
                    "domain": "b.fr",
                    "source": "candidate",
                    "fiche": FICHE,
                    "siret": SIRET,
                },
                {"domain": "m.fr", "source": "manual", "fiche": None, "siret": SIRET},
                {"domain": "d.fr", "source": "routed", "fiche": None, "siret": None},
            ],
        },
        {"uid": "y", "allowed_attached_email_domains": []},
    ]
    expected = (
        "oidc_providers:\n"
        '  - uid: "x"\n'
        "    allowed_attached_email_domains:\n"
        "      - domain: a.fr\n"
        f"        fiche: {FICHE}\n"
        f'        siret: "{SIRET}"\n'
        "        source: dila\n"
        "      - domain: c.fr\n"
        f"        fiche: {FICHE}\n"
        "        source: dila\n"
        "      - domain: b.fr\n"
        f"        fiche: {FICHE}\n"
        f'        siret: "{SIRET}"\n'
        "        source: candidate\n"
        "      - domain: m.fr\n"
        f'        siret: "{SIRET}"\n'
        "        source: manual\n"
        "      - domain: d.fr\n"
        "        source: routed\n"
        '  - uid: "y"\n'
        "    allowed_attached_email_domains: []\n"
    )
    rendered = render_proconnect_allowlist_yaml(entries)
    assert rendered == expected
    # The SIRET stays a string, not a YAML integer.
    assert yaml.safe_load(rendered)["oidc_providers"][0][
        "allowed_attached_email_domains"
    ] == [
        {"domain": "a.fr", "fiche": FICHE, "siret": SIRET, "source": "dila"},
        {"domain": "c.fr", "fiche": FICHE, "source": "dila"},
        {"domain": "b.fr", "fiche": FICHE, "siret": SIRET, "source": "candidate"},
        {"domain": "m.fr", "siret": SIRET, "source": "manual"},
        {"domain": "d.fr", "source": "routed"},
    ]


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


def test_render_yaml_refuses_a_fiche_that_could_inject_a_line():
    """A newline in a fiche URL must not add an entry: the renderer refuses it."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [
                {
                    "domain": "a.fr",
                    "source": "dila",
                    "fiche": FICHE + "\n      - domain: evil.fr",
                }
            ],
        }
    ]

    with pytest.raises(ValueError, match="Invalid fiche URL"):
        render_proconnect_allowlist_yaml(entries)


def test_render_yaml_refuses_a_dila_row_without_a_fiche():
    """api-partenaires rejects a dila row with no fiche: never render one."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [
                {"domain": "a.fr", "source": "dila", "fiche": None}
            ],
        }
    ]

    with pytest.raises(ValueError, match="Invalid fiche URL"):
        render_proconnect_allowlist_yaml(entries)


def test_render_yaml_refuses_a_siret_that_could_inject_a_line():
    """Only 14 digits may be written as a SIRET."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [
                {
                    "domain": "a.fr",
                    "source": "dila",
                    "fiche": FICHE,
                    "siret": '1"\n      - domain: evil.fr',
                }
            ],
        }
    ]

    with pytest.raises(ValueError, match="Invalid SIRET"):
        render_proconnect_allowlist_yaml(entries)


def test_render_yaml_refuses_an_unknown_source():
    """Only the sources api-partenaires knows may reach the file."""
    entries = [
        {
            "uid": "x",
            "allowed_attached_email_domains": [{"domain": "a.fr", "source": "DILA"}],
        }
    ]

    with pytest.raises(ValueError, match="Unknown allowlist source"):
        render_proconnect_allowlist_yaml(entries)


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


def test_suggest_domains_command_proposes_variants_when_dila_has_slug():
    """When {slug}.fr is already the org's DILA domain, the other spellings are
    still proposed; {slug}.fr itself is not (it is already authoritative)."""
    org = factories.OrganizationFactory(
        name="Aiglun",
        departement_code_insee="06",
        proconnect_domains={"dpnt": ["aiglun.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert set(domain_bucket(org, "candidates")) == {
        "aiglun06.fr",
        "mairie-aiglun.fr",
        "ville-aiglun.fr",
    }


def test_suggest_domains_command_skips_domains_another_collectivite_has_at_dila():
    """Candidates stay off a domain DILA gives to ANOTHER collectivité, even when
    the organization has DILA domains of its own."""
    org = factories.OrganizationFactory(
        name="Aiglun",
        departement_code_insee="06",
        proconnect_domains={"dpnt": ["aiglun.fr"]},
    )
    other = factories.OrganizationFactory(
        name="Autre",
        departement_code_insee="04",
        proconnect_domains={"dpnt": ["mairie-aiglun.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    other.refresh_from_db()
    assert set(domain_bucket(org, "candidates")) == {"aiglun06.fr", "ville-aiglun.fr"}
    assert domain_bucket(other, "dpnt") == ["mairie-aiglun.fr"]


def test_suggest_domains_command_homonyms_share_unclaimed_candidates():
    """Two homonym communes: a domain DILA gives to one stays off the other's
    candidates, but a domain nobody holds is a candidate for both."""
    colter1 = factories.OrganizationFactory(
        name="Xyz",
        departement_code_insee="01",
        proconnect_domains={"dpnt": ["mairie-xyz.fr"]},
    )
    colter2 = factories.OrganizationFactory(name="Xyz", departement_code_insee="02")
    call_command("proconnect_regen_candidate_domains")
    colter1.refresh_from_db()
    colter2.refresh_from_db()

    candidates1 = domain_bucket(colter1, "candidates")
    candidates2 = domain_bucket(colter2, "candidates")
    assert "mairie-xyz.fr" not in candidates1  # its own DILA domain
    assert "mairie-xyz.fr" not in candidates2  # colter1's DILA domain
    assert "xyz.fr" in candidates1
    assert "xyz.fr" in candidates2


def test_suggest_domains_command_adds_bzh_for_brittany():
    """Breton départements (22/29/35/44/56) also get a {slug}.bzh suggestion."""
    org = factories.OrganizationFactory(
        name="Brest",
        departement_code_insee="29",
        # brest.fr is the DILA domain -> not proposed; .bzh is.
        proconnect_domains={"dpnt": ["brest.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    candidates = domain_bucket(org, "candidates")
    assert "brest.bzh" in candidates
    assert "brest.fr" not in candidates


def test_suggest_domains_command_adds_regional_and_om_extensions():
    """Réunion (974) gets .re, Corsica (2A) gets .corsica, in addition to .fr."""
    # {slug}.fr is each org's DILA domain -> not proposed; the regional/OM
    # extension is.
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
    reunion_candidates = domain_bucket(reunion, "candidates")
    corsica_candidates = domain_bucket(corsica, "candidates")
    assert "saint-denis.re" in reunion_candidates
    assert "saint-denis.fr" not in reunion_candidates
    assert "ajaccio.corsica" in corsica_candidates
    assert "ajaccio.fr" not in corsica_candidates


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


def test_suggest_domains_command_proposes_candidates_when_rpnt_complete():
    """An org that already satisfies the full RPNT set gets candidates like any other."""
    org = factories.OrganizationFactory(
        name="Ville A",
        departement_code_insee="45",
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    assert "ville-a.fr" in domain_bucket(org, "candidates")


def test_suggest_domains_command_skips_discarded():
    """A discarded domain is never re-suggested into candidates."""
    org = factories.OrganizationFactory(
        name="Brest",
        departement_code_insee="29",
        proconnect_domains={"discarded": ["ville-brest.fr"], "dpnt": ["brest.fr"]},
    )
    call_command("proconnect_regen_candidate_domains")
    org.refresh_from_db()
    candidates = domain_bucket(org, "candidates")
    assert "ville-brest.fr" not in candidates
    # The rest is still suggested, the Breton .bzh included.
    assert "brest.bzh" in candidates
    assert domain_bucket(org, "discarded") == ["ville-brest.fr"]


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


def _body(response):
    """The text of a streamed response."""
    return b"".join(response.streaming_content).decode()


@allowlist_key_settings
def test_allowlist_api_route_serves_yaml_text_plain():
    """The route renders the built allowlist as text/plain YAML."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    org = _active_subscription(service, operator, ["sub.fr"], departement="42")
    org.service_public_url = FICHE
    org.siret = SIRET
    org.proconnect_domains = {"dpnt": ["dila.fr"], "manual": ["manual.fr"]}
    org.save()

    response = _get_allowlist()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = _body(response)
    assert body.startswith("oidc_providers:")
    assert 'uid: "idp-x"' in body
    parsed = yaml.safe_load(body)["oidc_providers"][0]["allowed_attached_email_domains"]
    assert {item["domain"]: item for item in parsed} == {
        "sub.fr": {  # live
            "domain": "sub.fr",
            "fiche": FICHE,
            "siret": SIRET,
            "source": "routed",
        },
        "dila.fr": {
            "domain": "dila.fr",
            "fiche": FICHE,
            "siret": SIRET,
            "source": "dila",
        },
        "manual.fr": {
            "domain": "manual.fr",
            "fiche": FICHE,
            "siret": SIRET,
            "source": "manual",
        },
    }


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
    assert _body(response).startswith("oidc_providers:")


@allowlist_key_settings
def test_allowlist_api_route_reflects_a_change_immediately():
    """Built per request: no cache to serve a stale allowlist to the next caller."""
    operator = factories.OperatorFactory()
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    assert 'uid: "idp-x"' in _body(_get_allowlist())

    late = _proconnect_service("idp-late")
    factories.OperatorServiceConfigFactory(operator=operator, service=late)
    assert 'uid: "idp-late"' in _body(_get_allowlist())


@allowlist_key_settings
def test_allowlist_api_route_fails_before_streaming_when_the_build_fails():
    """A build error is a 500, not a 200 cut short: the first chunk is read first."""

    def failing_build():
        raise RuntimeError("database down")
        yield  # pylint: disable=unreachable

    with mock.patch(
        "core.api.viewsets.proconnect.iter_proconnect_allowlist",
        side_effect=failing_build,
    ):
        with pytest.raises(RuntimeError):
            _get_allowlist()


def test_streamed_yaml_is_the_rendered_yaml():
    """The chunks, however small, join into exactly what render returns."""
    entries = [
        {
            "uid": "idp-x",
            "allowed_attached_email_domains": [
                {
                    "domain": f"d{i}.fr",
                    "source": "candidate",
                    "fiche": None,
                    "siret": None,
                }
                for i in range(7)
            ],
        },
        {"uid": "idp-empty", "allowed_attached_email_domains": []},
    ]
    with mock.patch("core.services.proconnect.YAML_CHUNK_LINES", 3):
        chunks = list(iter_proconnect_allowlist_yaml(entries))

    assert len(chunks) > 1
    assert "".join(chunks) == render_proconnect_allowlist_yaml(entries)
    assert chunks[0].startswith("oidc_providers:\n")


def test_build_allowlist_issues_the_same_queries_whatever_the_organization_count():
    """No per-organization query: subscriptions and organizations are read in bulk."""
    operator = factories.OperatorFactory(config={"departements": ["42"]})
    service = _proconnect_service("idp-x")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    _active_subscription(service, operator, ["a.fr"], departement="42")

    with CaptureQueriesContext(connection) as ctx:
        build_proconnect_allowlist()
    few = len(ctx.captured_queries)

    for i in range(10):
        _active_subscription(service, operator, [f"b{i}.fr"], departement="42")
    with CaptureQueriesContext(connection) as ctx:
        build_proconnect_allowlist()

    assert len(ctx.captured_queries) == few


def test_organization_in_the_scope_of_two_providers_feeds_both():
    """One read of the organization, a row for each provider that covers it."""
    operator_a = factories.OperatorFactory(config={"departements": ["42"]})
    operator_b = factories.OperatorFactory(config={"departements": ["42"]})
    service_a = _proconnect_service("idp-a")
    service_b = _proconnect_service("idp-b")
    factories.OperatorServiceConfigFactory(operator=operator_a, service=service_a)
    factories.OperatorServiceConfigFactory(operator=operator_b, service=service_b)
    org = factories.OrganizationFactory(departement_code_insee="42")
    update_proconnect_domains(org, candidates=["shared-scope.fr"])

    entries = {e["uid"]: _domains(e) for e in build_proconnect_allowlist()}

    assert entries == {"idp-a": ["shared-scope.fr"], "idp-b": ["shared-scope.fr"]}


def test_build_allowlist_does_not_query_the_operator_config_per_subscription():
    """The idp is read from the service: no lookup per subscription."""
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
    # One lookup of the operator configs, however many subscriptions.
    assert len(config_queries) <= 2, config_queries


# --- proconnect_fetch_prevalidated command -----------------------------------


@responses.activate
def test_fetch_prevalidated_caches_per_idp_allowlist():
    """The command caches each provider's allowed domains (empty set stays defined)."""
    yaml_text = (
        "oidc_providers:\n"
        '  - uid: "idp-x"\n'
        "    allowed_attached_email_domains:\n"
        "      - domain: b.fr\n"
        f"        fiche: {FICHE}\n"
        "        source: dila\n"
        "      - domain: a.fr\n"  # stored normalized + sorted
        "        source: routed\n"
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
    # The fetched file covers every provider, so one it does not mention has
    # nothing deployed — empty, not unknown.
    assert get_prevalidated_domains("idp-z") == []


@responses.activate
def test_fetch_prevalidated_keeps_the_previous_entry_for_a_malformed_provider():
    """A provider without a domains *list* keeps what the last fetch cached for it."""
    store_prevalidated_domains("idp-x", ["kept.fr"])
    responses.add(
        responses.GET,
        "https://allowlist.test/x.yaml",
        body=(
            "oidc_providers:\n"
            '  - uid: "idp-x"\n'
            "    allowed_attached_email_domains: null\n"
            '  - uid: "idp-y"\n'
            "    allowed_attached_email_domains:\n"
            "      - domain: y.fr\n"
            "        source: routed\n"
        ),
        status=200,
    )

    call_command(
        "proconnect_fetch_prevalidated",
        "--url",
        "https://allowlist.test/x.yaml",
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert get_prevalidated_domains("idp-x") == ["kept.fr"]
    assert get_prevalidated_domains("idp-y") == ["y.fr"]


@responses.activate
def test_fetch_prevalidated_keeps_the_previous_entry_when_no_entry_is_readable():
    """A non-empty list we cannot read a domain from (a format we do not know)
    must not be cached as "nothing pre-validated"."""
    store_prevalidated_domains("idp-x", ["kept.fr"])
    responses.add(
        responses.GET,
        "https://allowlist.test/x.yaml",
        body=(
            "oidc_providers:\n"
            '  - uid: "idp-x"\n'
            "    allowed_attached_email_domains:\n"
            "      - fqdn: new.fr\n"
            "      - just-a-string.fr\n"
        ),
        status=200,
    )
    err = StringIO()

    call_command(
        "proconnect_fetch_prevalidated",
        "--url",
        "https://allowlist.test/x.yaml",
        stdout=StringIO(),
        stderr=err,
    )

    assert get_prevalidated_domains("idp-x") == ["kept.fr"]
    assert "idp-x: no readable" in err.getvalue()


@responses.activate
def test_fetch_prevalidated_drops_a_provider_the_new_file_omits():
    """The file is authoritative: a uid it no longer lists has nothing deployed."""
    store_prevalidated_domains("idp-gone", ["stale.fr"])
    responses.add(
        responses.GET,
        "https://allowlist.test/x.yaml",
        body='oidc_providers:\n  - uid: "idp-x"\n    allowed_attached_email_domains: []\n',
        status=200,
    )

    call_command(
        "proconnect_fetch_prevalidated",
        "--url",
        "https://allowlist.test/x.yaml",
        stdout=StringIO(),
    )

    assert get_prevalidated_domains("idp-gone") == []


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
def test_fetch_prevalidated_never_loads_the_whole_document():
    """The deployed file is tens of MB: loaded whole, the cron container ran out of
    memory and was killed without a trace. It is read as a stream of events."""
    responses.add(
        responses.GET,
        "https://allowlist.test/x.yaml",
        body='oidc_providers:\n  - uid: "idp-x"\n    allowed_attached_email_domains:\n'
        "      - domain: a.fr\n",
        status=200,
    )

    with (
        mock.patch("yaml.safe_load", side_effect=AssertionError("whole document")),
        mock.patch("yaml.load", side_effect=AssertionError("whole document")),
    ):
        call_command(
            "proconnect_fetch_prevalidated",
            "--url",
            "https://allowlist.test/x.yaml",
            stdout=StringIO(),
        )

    assert get_prevalidated_domains("idp-x") == ["a.fr"]


@responses.activate
def test_fetch_prevalidated_caches_nothing_when_the_yaml_breaks_halfway():
    """Providers read before a syntax error are not worth a half-written cache."""
    store_prevalidated_domains("idp-x", ["kept.fr"])
    responses.add(
        responses.GET,
        "https://allowlist.test/x.yaml",
        body=(
            "oidc_providers:\n"
            '  - uid: "idp-new"\n'
            "    allowed_attached_email_domains: []\n"
            '  - uid: "idp-x"\n'
            "    allowed_attached_email_domains: [unclosed\n"
        ),
        status=200,
    )

    with pytest.raises(CommandError, match="Invalid YAML"):
        call_command(
            "proconnect_fetch_prevalidated", "--url", "https://allowlist.test/x.yaml"
        )

    assert get_prevalidated_domains("idp-x") == ["kept.fr"]
    assert get_prevalidated_domains("idp-new") == []  # not in the cached map either


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", []),
        ("---\n", []),
        ("null\n", []),
        ("other: 1\n", []),
        ("oidc_providers:\n", []),
        ("oidc_providers: []\n", []),
        # Comments, quoting styles, flow style and extra keys are all YAML to it.
        (
            "# header\n"
            "version: 2\n"
            "oidc_providers:\n"
            "  - uid: 'a'  # single quoted\n"
            "    name: {x: [1, 2]}\n"
            "    allowed_attached_email_domains:\n"
            '      - {domain: "x.fr", source: dila}\n'
            "      - domain: y.fr\n"
            "        extra: [1, {k: v}]\n"
            "    trailing: [a, b]\n",
            [("a", ["x.fr", "y.fr"])],
        ),
        # What it cannot read comes back as None, for the caller to decide.
        (
            "oidc_providers:\n"
            "  - uid: null\n"
            "    allowed_attached_email_domains: []\n"
            "  - just a string\n"
            "  - [a, list]\n"
            "  - uid: b\n"
            "    allowed_attached_email_domains: ~\n"
            "  - uid: c\n"
            "    allowed_attached_email_domains: scalar\n"
            "  - uid: d\n"
            "    allowed_attached_email_domains:\n"
            "      - fqdn: z.fr\n"
            "      - plain.fr\n"
            "      - domain: ~\n"
            "      - [nested]\n"
            "      - domain: ok.fr\n",
            [
                (None, []),
                (None, None),
                (None, None),
                ("b", None),
                ("c", None),
                ("d", [None, None, None, None, "ok.fr"]),
            ],
        ),
        # A key that is not a scalar is skipped with its value.
        (
            "oidc_providers:\n"
            "  - uid: e\n"
            "    ? [complex, key]\n"
            "    : ignored\n"
            "    allowed_attached_email_domains: []\n",
            [("e", [])],
        ),
    ],
)
def test_iter_allowlist_providers_reads_the_shapes_the_command_cares_about(
    text, expected
):
    """The event reader agrees with what `yaml.safe_load` gave the command."""
    assert list(iter_allowlist_providers(io.BytesIO(text.encode()))) == expected


@pytest.mark.parametrize(
    "text, kind", [("- a\n- b\n", "list"), ("just text\n", "scalar")]
)
def test_iter_allowlist_providers_refuses_a_document_that_is_not_a_mapping(text, kind):
    """The command turns this into an error instead of caching nothing quietly."""
    with pytest.raises(AllowlistFormatError, match=f"got {kind}"):
        list(iter_allowlist_providers(io.BytesIO(text.encode())))


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
