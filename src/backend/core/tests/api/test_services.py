"""
Test users API endpoints in the deploycenter core app.
"""

from multiprocessing import context
from core.tests.utils import assert_equals_partial
import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


def test_api_organizations_services_list_anonymous():
    """Anonymous users should not be allowed to retrieve organization services."""
    factories.UserFactory.create_batch(2)
    client = APIClient()

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization)

    response = client.get(f"/api/v1.0/organizations/{organization.id}/services/")
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }

def test_api_organizations_services_list_authenticated():
    """Authenticated users should be able to retrieve organization services of an operator for which they have a UserOperatorRole."""
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
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization_ok1)
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization_ok2)
    factories.OperatorOrganizationRoleFactory(operator=operator2, organization=organization_nok1)
    factories.OperatorOrganizationRoleFactory(operator=operator2, organization=organization_nok2)

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    subscription = factories.ServiceSubscriptionFactory(organization=organization_ok1, service=service1)
    factories.ServiceSubscriptionFactory(organization=organization_nok1, service=service2)

    response = client.get(f"/api/v1.0/organizations/{organization_ok1.id}/services/")
    content = response.json()
    results = content["results"]
    assert len(results) == 2
    assert_equals_partial(results, [
        {
            "id": service1.id,
            "name": service1.name,
            "subscription": {
                "id": str(subscription.id),
            }
        },
        {
            "id": service2.id,
            "name": service2.name,
            "subscription": None
        }
    ])

     
    # Test the list of organizations with services
    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    content = response.json()
    results = content["results"]
    assert len(results) == 2
    assert_equals_partial(results, [
        {
            "id": str(organization_ok1.id),
            "name": organization_ok1.name,
            "service_subscriptions": [
                {
                    "service": {
                        "id": service1.id,
                        "name": service1.name,
                    }
                }
            ]
        },
        {
            "id": str(organization_ok2.id),
            "name": organization_ok2.name,
        }
    ])

def test_api_organization_service_enable_disable():
    """Authenticated users should be able to enable and disable a service for an organization."""    
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
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization_ok1)
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization_ok2)
    factories.OperatorOrganizationRoleFactory(operator=operator2, organization=organization_nok1)
    factories.OperatorOrganizationRoleFactory(operator=operator2, organization=organization_nok2)

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(organization=organization_nok1, service=service2)
    
    # Test that no subscription exists
    response = client.get(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/")
    assert response.status_code == 404

    # Test that the subscription can be created
    response = client.post(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/", {})
    assert response.status_code == 201
    content_created = response.json()
    assert "id" in content_created
    assert "metadata" in content_created
    assert "created_at" in content_created

    # Test that the subscription exists
    response = client.get(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/")
    assert response.status_code == 200
    content_retrieved = response.json()
    assert_equals_partial(content_retrieved, content_created)

    # Test that the subscription can be deleted
    response = client.delete(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/{content_created['id']}/")
    assert response.status_code == 204

    # Test that the subscription does not exist
    response = client.get(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/")
    assert response.status_code == 404

def test_api_organization_service_enable_disable_no_role():
    """Authenticated users should not be able to enable and disable a service for an organization for which they have no UserOperatorRole."""
    """Authenticated users should be able to enable and disable a service for an organization."""    
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user2)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization_ok1)
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization_ok2)
    factories.OperatorOrganizationRoleFactory(operator=operator2, organization=organization_nok1)
    factories.OperatorOrganizationRoleFactory(operator=operator2, organization=organization_nok2)

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    subscription = factories.ServiceSubscriptionFactory(organization=organization_ok1, service=service1)
    
    # Test that it cannot be retrieved
    response = client.get(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/")
    assert response.status_code == 403

    # Test that the subscription cannot be created
    response = client.post(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/", {})
    assert response.status_code == 403

    # Test that the subscription cannot be deleted
    response = client.delete(f"/api/v1.0/organizations/{organization_ok1.id}/services/{service1.id}/subscription/{subscription.id}/")
    assert response.status_code == 403