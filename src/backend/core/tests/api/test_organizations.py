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

    response = client.get(f"/api/v1.0/organizations/{organization_ok1.id}/")
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

    response = client.get(f"/api/v1.0/organizations/{organization_nok1.id}/")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }
