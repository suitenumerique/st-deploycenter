"""
Test subscription entitlements API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db


def test_api_subscription_entitlements_anonymous():
    """Anonymous users should not be able to list entitlements."""
    user = factories.UserFactory()
    client = APIClient()
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization_ok1 = factories.OrganizationFactory(name="A")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    service1 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 401


def test_api_subscription_entitlements_no_role():
    """Users without the proper operator role should not be able to list entitlements."""
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user2, operator=operator)
    factories.UserOperatorRoleFactory(user=user, operator=operator2)
    organization_ok1 = factories.OrganizationFactory(name="A")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    service1 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 403


def test_api_subscription_entitlements_list():
    """Authenticated users should be able to list entitlements for a service subscription."""
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

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_nok1, service=service2, operator=operator2
    )

    # Test that the subscription can be created
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 201

    # Test that the entitlements can be listed but are empty
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0

    service_subscription = models.ServiceSubscription.objects.get(
        organization=organization_ok1, service=service1, operator=operator
    )
    entitlement = factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
    )

    # Test that the entitlements can be listed and are not empty
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "count": 1,
            "results": [
                {
                    "id": str(entitlement.id),
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "config": {
                        "max_storage": 1000,
                    },
                    "account_type": "",
                    "account_id": "",
                }
            ],
        },
    )

    # Test that there is not collision between organizations and services.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service2.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok2.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0


def test_api_subscription_entitlements_list_filtering():
    """Authenticated users should be able to filter entitlements by account_type, account_id, and type."""
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

    service1 = factories.ServiceFactory()
    factories.ServiceFactory()
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )

    factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="",
        account_id="",
    )

    entitlement_with_account = factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="user",
        account_id="xyz",
    )

    # Test that the entitlements can be listed and are not empty
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2

    # Test that the entitlements can be filtered by account type.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
        query_params={
            "account_type": "user",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["id"] == str(entitlement_with_account.id)

    # Test that the entitlements can be filtered by account id.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
        query_params={
            "account_id": "xyz",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["id"] == str(entitlement_with_account.id)

    # Test that the entitlements can be filtered by type.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
        query_params={
            "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2

    # Test that the entitlements can be filtered by type that does not exist.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
        query_params={
            "type": "test_type",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0


def test_api_subscription_entitlements_patch():
    """Authenticated users should be able to update entitlements."""
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

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_nok1, service=service2, operator=operator2
    )

    subscription = factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )
    entitlement = factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
    )

    # Test that the entitlement can be retrieved
    response = client.get(
        f"/api/v1.0/entitlements/{entitlement.id}/",
        format="json",
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "id": str(entitlement.id),
            "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
            "config": {
                "max_storage": 1000,
            },
            "account_type": "",
            "account_id": "",
        },
    )

    # Test that the entitlement can be patched
    response = client.patch(
        f"/api/v1.0/entitlements/{entitlement.id}/",
        {
            "config": {
                "max_storage": 2000,
            },
        },
        format="json",
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "id": str(entitlement.id),
            "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
            "config": {
                "max_storage": 2000,
            },
            "account_type": "",
            "account_id": "",
        },
    )


def test_api_subscription_entitlements_cannot_patch_role():
    """Authenticated users should not be able to patch entitlements if they have no UserOperatorRole."""
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

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_nok1, service=service2, operator=operator2
    )

    subscription = factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )
    entitlement = factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
    )

    # Test that the entitlement cannot be patched
    response = client.patch(
        f"/api/v1.0/entitlements/{entitlement.id}/",
        {
            "config": {
                "max_storage": 2000,
            },
        },
        format="json",
    )
    assert response.status_code == 403
