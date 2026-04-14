"""
Test external service API key authentication and scoping.
"""

import pytest
from rest_framework.test import APIClient

from core import factories, models

pytestmark = pytest.mark.django_db


def _setup_service_with_key(service_type="test_service"):
    """Create a service with an external management API key and associated fixtures."""
    api_key = "test-service-api-key-12345"
    operator = factories.OperatorFactory()
    service = factories.ServiceFactory(type=service_type)
    service.external_management_api_key = api_key
    service.save()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
    return client, operator, service, organization


# --- Authentication tests ---


def test_service_api_key_valid():
    """Test that a valid service API key authenticates successfully."""
    client, operator, service, organization = _setup_service_with_key()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 200


def test_service_api_key_invalid():
    """Test that an invalid service API key is rejected."""
    client, operator, service, organization = _setup_service_with_key()
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid-key")

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 401


def test_service_api_key_missing():
    """Test that a missing API key is rejected."""
    _client, operator, service, organization = _setup_service_with_key()
    client = APIClient()

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 401


def test_service_api_key_unconfigured_operator():
    """Test that a service key is rejected for an operator without OperatorServiceConfig."""
    api_key = "test-service-api-key-99999"
    service = factories.ServiceFactory(type="test_service")
    service.external_management_api_key = api_key
    service.save()

    # Create operator WITHOUT OperatorServiceConfig for this service
    other_operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=other_operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    response = client.patch(
        f"/api/v1.0/operators/{other_operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 403


# --- Subscription endpoint tests ---


def test_service_api_key_create_subscription():
    """Test creating a subscription for the authenticated service."""
    client, operator, service, organization = _setup_service_with_key()

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 201
    content = response.json()
    assert "metadata" in content
    assert "is_active" in content


def test_service_api_key_get_subscription():
    """Test getting a subscription for the authenticated service."""
    client, operator, service, organization = _setup_service_with_key()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 200


def test_service_api_key_delete_subscription():
    """Test deleting a subscription for the authenticated service."""
    client, operator, service, organization = _setup_service_with_key()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    response = client.delete(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/"
    )
    assert response.status_code == 204


def test_service_api_key_cannot_access_other_service_subscription():
    """Test that a service key cannot manage subscriptions for a different service."""
    client, operator, _service, organization = _setup_service_with_key()

    other_service = factories.ServiceFactory(type="other_service")
    factories.OperatorServiceConfigFactory(operator=operator, service=other_service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{other_service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 403


def test_service_api_key_cannot_get_other_service_subscription():
    """Test that a service key cannot read subscriptions for a different service."""
    client, operator, _service, organization = _setup_service_with_key()

    other_service = factories.ServiceFactory(type="other_service")
    factories.OperatorServiceConfigFactory(operator=operator, service=other_service)
    factories.ServiceSubscriptionFactory(
        organization=organization, service=other_service, operator=operator
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{other_service.id}/subscription/"
    )
    assert response.status_code == 403


# --- Entitlement endpoint tests ---


def test_service_api_key_list_entitlements():
    """Test listing entitlements for the authenticated service."""
    client, operator, service, organization = _setup_service_with_key()
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account=None,
        config={"max_storage": 100},
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/entitlements/"
    )
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_service_api_key_cannot_list_other_service_entitlements():
    """Test that a service key cannot list entitlements for a different service."""
    client, operator, _service, organization = _setup_service_with_key()

    other_service = factories.ServiceFactory(type="other_service")
    factories.OperatorServiceConfigFactory(operator=operator, service=other_service)
    sub = factories.ServiceSubscriptionFactory(
        organization=organization, service=other_service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=sub,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account=None,
        config={"max_storage": 100},
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{other_service.id}/subscription/entitlements/"
    )
    assert response.status_code == 403


# --- Access denied tests ---


def test_service_api_key_cannot_list_organizations():
    """Test that a service key cannot list organizations."""
    client, operator, _service, _organization = _setup_service_with_key()

    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    assert response.status_code == 401


def test_service_api_key_cannot_access_accounts_list():
    """Test that a service key cannot list accounts."""
    client, operator, _service, organization = _setup_service_with_key()

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"
    )
    assert response.status_code == 401


def test_service_api_key_cannot_create_account():
    """Test that a service key cannot create accounts."""
    client, operator, _service, organization = _setup_service_with_key()

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/",
        {"email": "test@example.com", "type": "user"},
        format="json",
    )
    assert response.status_code == 401


def test_service_api_key_cannot_update_account():
    """Test that a service key cannot update accounts."""
    client, _operator, _service, organization = _setup_service_with_key()
    account = factories.AccountFactory(organization=organization, type="user")

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/",
        {"email": "new@example.com"},
        format="json",
    )
    assert response.status_code == 401


def test_service_api_key_cannot_delete_account():
    """Test that a service key cannot delete accounts."""
    client, _operator, _service, organization = _setup_service_with_key()
    account = factories.AccountFactory(organization=organization, type="user")

    response = client.delete(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 401


def test_service_api_key_cannot_update_service_link():
    """Test that a service key cannot update account service links."""
    client, _operator, service, organization = _setup_service_with_key()
    account = factories.AccountFactory(organization=organization, type="user")

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/services/{service.id}/",
        {"roles": ["admin"]},
        format="json",
    )
    assert response.status_code == 401


def test_service_api_key_cannot_access_unmanaged_organization():
    """Test that a service key cannot access an organization not managed by the operator."""
    client, operator, service, _organization = _setup_service_with_key()

    # Create an organization NOT managed by this operator
    unmanaged_org = factories.OrganizationFactory()

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{unmanaged_org.id}/"
        f"services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 403


# --- Coexistence tests ---


def test_operator_key_still_works():
    """Test that operator external management key still works after adding service key support."""
    operator = factories.OperatorFactory()
    api_key = "test-operator-api-key-12345"
    operator.external_management_api_key = api_key
    operator.save()

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"
    )
    assert response.status_code == 200


def test_both_keys_coexist():
    """Test that operator and service keys can coexist."""
    operator = factories.OperatorFactory()
    op_key = "test-operator-api-key-coexist"
    operator.external_management_api_key = op_key
    operator.save()

    service = factories.ServiceFactory(type="test_service")
    svc_key = "test-service-api-key-coexist"
    service.external_management_api_key = svc_key
    service.save()

    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    # Operator key works
    op_client = APIClient()
    op_client.credentials(HTTP_AUTHORIZATION=f"Bearer {op_key}")
    response = op_client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"
    )
    assert response.status_code == 200

    # Service key works
    svc_client = APIClient()
    svc_client.credentials(HTTP_AUTHORIZATION=f"Bearer {svc_key}")
    response = svc_client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 201
