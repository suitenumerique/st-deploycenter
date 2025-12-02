"""
Test external API endpoints for organization and subscription management.
"""

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


def test_external_api_organization_lookup_by_siret_search():
    """Test organization search by SIRET using external API key."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization1 = factories.OrganizationFactory(
        siret="12345678901234", name="Test Organization 1"
    )
    organization2 = factories.OrganizationFactory(
        siret="98765432109876", name="Other Organization"
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization2
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    # Test searching organizations by SIRET
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?search=12345678901234"
    )
    assert response.status_code == 200
    content = response.json()
    results = content["results"]
    assert len(results) == 1
    assert results[0]["siret"] == "12345678901234"


def test_external_api_organization_lookup_by_siren_search():
    """Test organization search by SIREN using external API key."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization1 = factories.OrganizationFactory(
        siren="123456789", name="Test Organization 1"
    )
    organization2 = factories.OrganizationFactory(
        siren="987654321", name="Other Organization"
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization2
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    # Test searching organizations by SIREN
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?search=123456789"
    )
    assert response.status_code == 200
    content = response.json()
    results = content["results"]
    assert len(results) == 1
    assert results[0]["siren"] == "123456789"


def test_external_api_create_subscription():
    """Test creating a subscription using external API key."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory(siret="12345678901234")
    service = factories.ServiceFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    # Create subscription
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 201, (
        f"Expected 201, got {response.status_code}. "
        f"Response: {response.json() if response.status_code != 201 else 'OK'}"
    )
    content = response.json()
    assert "metadata" in content
    assert "created_at" in content
    assert "is_active" in content

    # Verify subscription exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 200
    content_retrieved = response.json()
    assert content_retrieved["metadata"] == content["metadata"]
    assert content_retrieved["created_at"] == content["created_at"]
    assert content_retrieved["is_active"] == content["is_active"]

    # Test creating subscription with is_active=False
    organization2 = factories.OrganizationFactory(siret="98765432109876")
    service2 = factories.ServiceFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization2
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization2.id}/"
        f"services/{service2.id}/subscription/",
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 201
    content = response.json()
    assert content["is_active"] is False

    # Verify subscription exists and is inactive
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization2.id}/"
        f"services/{service2.id}/subscription/"
    )
    assert response.status_code == 200
    content_retrieved = response.json()
    assert content_retrieved["is_active"] is False


def test_external_api_delete_subscription():
    """Test deleting a subscription using external API key."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory(siret="12345678901234")
    service = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    # Verify subscription exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 200

    # Delete subscription
    response = client.delete(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 204

    # Verify subscription no longer exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 404


def test_external_api_invalid_api_key():
    """Test that invalid API key is rejected."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid-key")

    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    assert response.status_code == 401


def test_external_api_missing_api_key():
    """Test that missing API key is rejected."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()

    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    assert response.status_code == 401


def test_external_api_wrong_operator():
    """Test that API key from one operator cannot access another operator's data."""
    operator1 = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    api_key1 = "test-external-api-key-12345"
    api_key2 = "test-external-api-key-67890"
    operator1.config = {"external_management_api_key": api_key1}
    operator1.save()
    operator2.config = {"external_management_api_key": api_key2}
    operator2.save()

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator1, organization=organization
    )

    client = APIClient()
    # Use operator1's key but try to access operator2's endpoint
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key1}")

    response = client.get(f"/api/v1.0/operators/{operator2.id}/organizations/")
    assert response.status_code == 401


def test_external_api_organization_read_only():
    """Test that external API can only read organizations, not modify them."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    # Try to update organization (should fail - read-only)
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/",
        {"name": "New Name"},
    )
    # ReadOnlyModelViewSet doesn't support PATCH, so it should return 405 Method Not Allowed
    assert response.status_code == 405

    # Try to delete organization (should fail - read-only)
    response = client.delete(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
    )
    assert response.status_code == 405


def test_external_api_subscription_post_not_allowed():
    """Test that POST method is not allowed for subscription endpoint via external API."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 405


def test_external_api_subscription_put_not_allowed():
    """Test that PUT method is not allowed for subscription endpoint via external API."""
    operator = factories.OperatorFactory()
    api_key = "test-external-api-key-12345"
    operator.config = {"external_management_api_key": api_key}
    operator.save()

    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    response = client.put(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 405
