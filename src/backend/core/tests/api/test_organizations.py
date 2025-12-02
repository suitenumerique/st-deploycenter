"""
Test users API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
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
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
    )
    content = response.json()
    results = content
    assert_equals_partial(
        results,
        {
            "id": str(organization_ok1.id),
            "name": organization_ok1.name,
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
