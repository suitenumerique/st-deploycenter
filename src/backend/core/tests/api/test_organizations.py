"""
Test users API endpoints in the deploycenter core app.
"""

import json

from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.test import override_settings

import pytest
import responses
from rest_framework.test import APIClient

from core import factories
from core.models import Organization
from core.services.proconnect import store_prevalidated_domains
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db


def test_api_organizations_list_anonymous():
    """Anonymous users should not be allowed to list operators."""
    factories.UserFactory.create_batch(2)
    client = APIClient()

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }


def test_api_organizations_list_authenticated():
    """
    Authenticated users should be able to list organizations of an
    operator for which they have a UserOperatorRole.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory(name="C")
    organization_nok2 = factories.OrganizationFactory(name="D")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    content = response.json()
    results = content["results"]
    assert len(results) == 2
    assert_equals_partial(
        results,
        [
            {
                "id": str(organization_ok1.id),
                "name": organization_ok1.name,
            },
            {
                "id": str(organization_ok2.id),
                "name": organization_ok2.name,
            },
        ],
    )

    response = client.get(f"/api/v1.0/operators/{operator2.id}/organizations/")
    assert response.status_code == 403


def test_api_organizations_list_authenticated_order_by():
    """
    Authenticated users should be able to list and order organizations of an
    operator for which they have a UserOperatorRole.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A", epci_libelle="M")
    organization_ok2 = factories.OrganizationFactory(name="B", epci_libelle="N")
    organization_ok3 = factories.OrganizationFactory(name="C", epci_libelle="O")
    organization_ok4 = factories.OrganizationFactory(name="D", epci_libelle="P")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok3
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok4
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?ordering=name"
    )
    content = response.json()
    results = content["results"]
    assert len(results) == 4
    assert_equals_partial(
        results,
        [
            {
                "id": str(organization_ok1.id),
                "name": organization_ok1.name,
            },
            {
                "id": str(organization_ok2.id),
                "name": organization_ok2.name,
            },
            {
                "id": str(organization_ok3.id),
                "name": organization_ok3.name,
            },
            {
                "id": str(organization_ok4.id),
                "name": organization_ok4.name,
            },
        ],
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?ordering=-name"
    )
    content = response.json()
    results = content["results"]
    assert len(results) == 4
    assert_equals_partial(
        results,
        [
            {
                "id": str(organization_ok4.id),
                "name": organization_ok4.name,
            },
            {
                "id": str(organization_ok3.id),
                "name": organization_ok3.name,
            },
            {
                "id": str(organization_ok2.id),
                "name": organization_ok2.name,
            },
            {
                "id": str(organization_ok1.id),
                "name": organization_ok1.name,
            },
        ],
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?ordering=epci_libelle"
    )
    content = response.json()
    results = content["results"]
    assert len(results) == 4
    assert_equals_partial(
        results,
        [
            {
                "id": str(organization_ok1.id),
                "epci_libelle": organization_ok1.epci_libelle,
            },
            {
                "id": str(organization_ok2.id),
                "epci_libelle": organization_ok2.epci_libelle,
            },
            {
                "id": str(organization_ok3.id),
                "epci_libelle": organization_ok3.epci_libelle,
            },
            {
                "id": str(organization_ok4.id),
                "epci_libelle": organization_ok4.epci_libelle,
            },
        ],
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?ordering=-epci_libelle"
    )
    content = response.json()
    results = content["results"]
    assert len(results) == 4
    assert_equals_partial(
        results,
        [
            {
                "id": str(organization_ok4.id),
                "epci_libelle": organization_ok4.epci_libelle,
            },
            {
                "id": str(organization_ok3.id),
                "epci_libelle": organization_ok3.epci_libelle,
            },
            {
                "id": str(organization_ok2.id),
                "epci_libelle": organization_ok2.epci_libelle,
            },
            {
                "id": str(organization_ok1.id),
                "epci_libelle": organization_ok1.epci_libelle,
            },
        ],
    )


def test_api_organizations_list_authenticated_search():
    """
    Authenticated users should be able to list and search organizations of an
    operator for which they have a UserOperatorRole.

    Search is case insensitive and accent insensitive.
    The order of the results is based on the match priority: name first, then departement_code_insee, then epci_libelle.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(
        name="Évreux",
        epci_libelle="CA Evreux Portes de Normandie",
        departement_code_insee="27",
    )
    organization_ok2 = factories.OrganizationFactory(
        name="Bondoufle",
        epci_libelle="Communauté d'agglomération Évry Centre Essonne",
        departement_code_insee="91",
    )
    organization_ok3 = factories.OrganizationFactory(
        name="Paris", epci_libelle="CA Paris", departement_code_insee="75"
    )
    organization_ok4 = factories.OrganizationFactory(
        name="Truc",
        epci_libelle="CA Evreux Portes de Normandie",
        departement_code_insee="27",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok3
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok4
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?search=Evr"
    )
    content = response.json()
    results = content["results"]
    assert_equals_partial(
        results,
        [
            {
                "name": "Évreux",
                "epci_libelle": "CA Evreux Portes de Normandie",
            },
            {
                "name": "Bondoufle",
                "epci_libelle": "Communauté d'agglomération Évry Centre Essonne",
            },
            {
                "name": "Truc",
                "epci_libelle": "CA Evreux Portes de Normandie",
            },
        ],
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?search=Evreux"
    )
    content = response.json()
    results = content["results"]
    assert_equals_partial(
        results,
        [
            {
                "name": "Évreux",
                "epci_libelle": "CA Evreux Portes de Normandie",
            },
            {
                "name": "Truc",
                "epci_libelle": "CA Evreux Portes de Normandie",
            },
        ],
    )

    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/?search=91")
    content = response.json()
    results = content["results"]
    assert_equals_partial(
        results,
        [
            {
                "name": "Bondoufle",
                "epci_libelle": "Communauté d'agglomération Évry Centre Essonne",
            },
        ],
    )


def test_api_organizations_retrieve_authenticated():
    """
    Authenticated users should be able to retrieve organizations of an operator
    for which they have a UserOperatorRole.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
        proconnect_domains={"manual": ["extra.fr"], "candidates": ["commune.fr"]},
    )
    organization_ok2 = factories.OrganizationFactory()
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
    )
    content = response.json()
    results = content
    assert_equals_partial(
        results,
        {
            "id": str(organization_ok1.id),
            "name": organization_ok1.name,
            "mail_domain": "commune.fr",
            "mail_domain_status": Organization.MailDomainStatus.VALID,
            "proconnect_domains": {
                "requested": [],
                "manual": ["extra.fr"],
                "dpnt": [],
                "candidates": ["commune.fr"],
                "discarded": [],
            },
        },
    )


def test_api_organizations_retrieve_authenticated_no_role():
    """
    Authenticated users should not be able to retrieve organizations for which
    they have no UserOperatorRole.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory()
    organization_ok2 = factories.OrganizationFactory()
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    response = client.get(
        f"/api/v1.0/operators/{operator2.id}/organizations/{organization_nok1.id}/"
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


def _setup_org(user, **org_kwargs):
    """Create an operator the user belongs to, plus an org it manages."""
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(**org_kwargs)
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    return operator, organization


def test_api_organization_exposes_proconnect_domains_buckets():
    """The API sends raw proconnect_domains buckets; derived views live in the service."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user,
        proconnect_domains={"dpnt": ["commune.fr"], "manual": ["suggested.fr"]},
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "x"})
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["routed.fr"]},
        is_active=True,
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["proconnect_domains"]["dpnt"] == ["commune.fr"]
    assert data["proconnect_domains"]["manual"] == ["suggested.fr"]
    # Derived views are no longer serialized (the frontend computes them).
    assert "available_domains" not in data
    assert "domains_by_source" not in data


def _full(**buckets):
    """Expected full proconnect_domains dict with the given buckets set."""
    base = {
        "requested": [],
        "manual": [],
        "dpnt": [],
        "candidates": [],
        "discarded": [],
    }
    base.update(buckets)
    return base


def test_api_organization_proconnect_domains_superuser_updates_manual_only():
    """A superuser sets the manual bucket; system buckets are preserved."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, proconnect_domains={"candidates": ["kept-auto.fr"]}
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"manual": ["New.FR ", "b.fr", "b.fr"]},
        format="json",
    )
    assert response.status_code == 200
    # normalized: lowercased, trimmed, deduped, sorted (a malformed value is a
    # 400 — see test_api_organization_proconnect_domains_rejects_invalid_domains)
    assert response.json() == _full(
        manual=["b.fr", "new.fr"], candidates=["kept-auto.fr"]
    )
    organization.refresh_from_db()
    assert organization.proconnect_domains == _full(
        manual=["b.fr", "new.fr"], candidates=["kept-auto.fr"]
    )


def test_api_organization_proconnect_domains_change_creates_log_entry():
    """Domain add/remove is recorded as an admin LogEntry on the org."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(user, proconnect_domains={"manual": ["old.fr"]})

    client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"manual": ["new.fr"]},
        format="json",
    )
    entry = LogEntry.objects.filter(object_id=str(organization.pk)).latest(
        "action_time"
    )
    assert "added new.fr to manual" in entry.change_message
    assert "removed old.fr from manual" in entry.change_message


def test_api_organization_proconnect_domains_regular_user_cannot_set_manual():
    """A non-superuser cannot edit the validated (manual) bucket."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, proconnect_domains={"manual": ["keep.fr"]}
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"manual": ["hacked.fr"]},
        format="json",
    )
    assert response.status_code == 403
    organization.refresh_from_db()
    assert organization.proconnect_domains == {"manual": ["keep.fr"]}


def test_api_organization_proconnect_domains_regular_user_can_ask():
    """A non-superuser can request domains (ask bucket), preserving other buckets."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, proconnect_domains={"manual": ["m.fr"], "candidates": ["a.fr"]}
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"requested": ["Wanted.FR"]},
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == _full(
        manual=["m.fr"], candidates=["a.fr"], requested=["wanted.fr"]
    )


@responses.activate
@override_settings(
    PROCONNECT_REQUESTED_DOMAIN_WEBHOOKS=[
        {
            "url": "https://hooks.example.test/domain-ask",
            "method": "POST",
            "event_types": ["domain.requested"],
            "body": {
                "org": {"$val": "organization_name"},
                "requested": {"$val": "requested_domains"},
            },
        }
    ]
)
def test_api_organization_ask_fires_webhook():
    """Requesting a new domain fires the statically-configured webhook."""
    responses.add(
        responses.POST, "https://hooks.example.test/domain-ask", json={}, status=200
    )

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(user, name="Ma Collectivité")

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"requested": ["wanted.fr"]},
        format="json",
    )
    assert response.status_code == 200
    assert len(responses.calls) == 1
    body = json.loads(responses.calls[0].request.body)
    assert body == {"org": "Ma Collectivité", "requested": "wanted.fr"}


@override_settings(PROCONNECT_REQUESTED_DOMAIN_WEBHOOKS=[])
@responses.activate
def test_api_organization_ask_no_webhook_when_unconfigured():
    """With no webhook configured, asking makes no outbound call."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(user)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"requested": ["wanted.fr"]},
        format="json",
    )
    assert response.status_code == 200
    assert len(responses.calls) == 0


def test_api_organization_proconnect_domains_superuser_validates_ask():
    """A superuser validates an asked domain by moving it ask -> manual."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, proconnect_domains={"requested": ["wanted.fr"]}
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"manual": ["wanted.fr"], "requested": []},
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == _full(manual=["wanted.fr"])


def test_api_organization_proconnect_domains_rejects_invalid_domains():
    """A malformed domain is a 400, not a silent drop (the storage layer would
    discard it and the caller would get a 200 with its domain missing)."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(user, proconnect_domains={"manual": ["ok.fr"]})

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"manual": ["ok.fr", "Not A Domain.fr", "-bad-.fr", "http://x.fr/a"]},
        format="json",
    )
    assert response.status_code == 400
    detail = response.json()["manual"]
    for value in ("Not A Domain.fr", "-bad-.fr", "http://x.fr/a"):
        assert value in str(detail)

    # Nothing was written.
    organization.refresh_from_db()
    assert organization.proconnect_domains["manual"] == ["ok.fr"]


def test_api_organization_superuser_can_discard():
    """A superuser can add a domain to the discarded bucket."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, proconnect_domains={"candidates": ["slug.fr", "keep.fr"]}
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"discarded": ["slug.fr"]},
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == _full(
        candidates=["keep.fr", "slug.fr"], discarded=["slug.fr"]
    )


def test_api_organization_proconnect_domains_via_operator_api_key():
    """External operator API key (no user) can request but not validate — no 500."""
    operator = factories.OperatorFactory(external_management_api_key="op-key-123456")
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer op-key-123456")
    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/"
        f"{organization.id}/proconnect-domains/"
    )

    # "requested" is allowed (no user → no LogEntry, no crash).
    response = client.patch(url, {"requested": ["x.fr"]}, format="json")
    assert response.status_code == 200
    assert response.json()["requested"] == ["x.fr"]

    # "manual" requires a superuser — an API key is not one.
    response = client.patch(url, {"manual": ["y.fr"]}, format="json")
    assert response.status_code == 403


def test_api_organization_regular_user_cannot_discard():
    """A non-superuser cannot write the discarded bucket."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, proconnect_domains={"candidates": ["slug.fr"]}
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/proconnect-domains/",
        {"discarded": ["slug.fr"]},
        format="json",
    )
    assert response.status_code == 403


@responses.activate
@override_settings(
    PROCONNECT_REQUESTED_DOMAIN_WEBHOOKS=[
        {
            "url": "https://hooks.example.test/domain-ask",
            "method": "POST",
            "event_types": ["domain.requested"],
            "body": {
                "org": {"$val": "organization_name"},
                "requested": {"$val": "requested_domains"},
            },
        }
    ]
)
def test_api_organization_ask_webhook_only_for_newly_requested():
    """The webhook fires only for domains newly added to 'requested', not on re-submits."""
    responses.add(
        responses.POST, "https://hooks.example.test/domain-ask", json={}, status=200
    )
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(
        user, name="Ma Collectivité", proconnect_domains={"requested": ["old.fr"]}
    )
    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/"
        f"{organization.id}/proconnect-domains/"
    )

    # Re-submitting an already-requested domain adds nothing new -> no webhook.
    response = client.patch(url, {"requested": ["old.fr"]}, format="json")
    assert response.status_code == 200
    assert len(responses.calls) == 0

    # Adding a genuinely new one fires exactly one webhook, for that domain only.
    response = client.patch(url, {"requested": ["old.fr", "new.fr"]}, format="json")
    assert response.status_code == 200
    assert len(responses.calls) == 1
    body = json.loads(responses.calls[0].request.body)
    assert body == {"org": "Ma Collectivité", "requested": "new.fr"}


def test_api_organization_api_key_request_writes_no_logentry():
    """An external-API-key request (no user) must not write a null-user LogEntry."""
    operator = factories.OperatorFactory(external_management_api_key="op-key-654321")
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer op-key-654321")

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/"
        f"{organization.id}/proconnect-domains/",
        {"requested": ["x.fr"]},
        format="json",
    )
    assert response.status_code == 200
    assert not LogEntry.objects.exists()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Isolate the prevalidation cache between tests.

    An inline cache.clear() at the end of a test is skipped when an assertion
    above it fails, leaking the cached allowlist into the next test.
    """
    cache.clear()


def _setup_proconnect_operator_org(user, **org_kwargs):
    """An operator with a proconnect service configured + a managed org."""
    operator, organization = _setup_org(user, **org_kwargs)
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp-x"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    return operator, organization


def test_api_organization_exposes_the_routable_domains():
    """The API decides what may be routed; the UI does not re-derive it."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_proconnect_operator_org(
        user,
        proconnect_domains={
            "manual": ["m.fr"],
            "candidates": ["c.fr", "gone.fr"],
            "dpnt": ["d.fr"],
            "requested": ["ask.fr"],
            "discarded": ["gone.fr", "d.fr"],
        },
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    assert response.status_code == 200
    # d.fr is DILA (a discard cannot hide it), gone.fr is discarded, ask.fr is
    # only a pending request.
    assert response.json()["proconnect_routable"] == ["c.fr", "d.fr", "m.fr"]
    # The raw buckets are still there, for the per-domain provenance display.
    assert response.json()["proconnect_domains"]["requested"] == ["ask.fr"]


def test_api_organization_proconnect_domains_prevalidated_intersection():
    """proconnect_prevalidated is the org's domains already in the deployed allowlist."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_proconnect_operator_org(
        user,
        proconnect_domains={"manual": ["a.fr", "pending.fr"], "candidates": ["c.fr"]},
    )
    store_prevalidated_domains("idp-x", ["a.fr", "c.fr", "unrelated.fr"])

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    assert response.status_code == 200
    prevalidated = response.json()["proconnect_prevalidated"]
    # Per-idp: a.fr/c.fr are deployed on idp-x; pending.fr isn't; unrelated.fr
    # isn't the org's.
    assert set(prevalidated["idp-x"]) == {"a.fr", "c.fr"}


def test_api_organization_proconnect_domains_prevalidation_unknown():
    """proconnect_prevalidated is null when the deployed allowlist is not cached."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_proconnect_operator_org(
        user, proconnect_domains={"manual": ["a.fr"]}
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    assert response.status_code == 200
    assert response.json()["proconnect_prevalidated"] is None


def test_api_organization_proconnect_domains_prevalidated_empty_but_defined():
    """An empty-but-defined allowlist yields {idp: []} (all 'not yet')."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_proconnect_operator_org(
        user, proconnect_domains={"manual": ["a.fr"]}
    )
    store_prevalidated_domains("idp-x", [])  # defined, but empty

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    assert response.status_code == 200
    # idp-x is known (present) but nothing is pre-validated yet.
    assert response.json()["proconnect_prevalidated"] == {"idp-x": []}


def test_api_organization_proconnect_domains_prevalidated_is_per_idp():
    """A domain deployed on one idp is not shown pre-validated for another idp."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization = _setup_org(user, proconnect_domains={"manual": ["a.fr"]})
    for idp in ("idp-a", "idp-b"):
        service = factories.ServiceFactory(type="proconnect", config={"idp_id": idp})
        factories.OperatorServiceConfigFactory(operator=operator, service=service)
    store_prevalidated_domains("idp-a", ["a.fr"])  # deployed on idp-a
    store_prevalidated_domains("idp-b", [])  # NOT on idp-b

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    prevalidated = response.json()["proconnect_prevalidated"]
    assert prevalidated["idp-a"] == ["a.fr"]
    assert prevalidated["idp-b"] == []
