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
                    "account": None,
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
    """Authenticated users should be able to filter entitlements by account_type, account__external_id, and type."""
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
        account=None,
    )

    entitlement_with_account_type = factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="user",
        account=None,
    )

    account = factories.AccountFactory(
        organization=organization_ok1,
        type="user",
        external_id="xyz",
    )
    entitlement_with_account = factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="user",
        account=account,
    )

    # Test that the entitlements can be listed and are not empty
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3

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
    assert data["count"] == 2
    ids = [result["id"] for result in data["results"]]
    assert str(entitlement_with_account.id) in ids
    assert str(entitlement_with_account_type.id) in ids

    # Test that the entitlements can be filtered by account external id.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/entitlements/",
        format="json",
        query_params={
            "account__external_id": "xyz",
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
            "account__id": account.id,
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
            "account": None,
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
            "account": None,
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


def test_api_subscription_create_with_entitlements():
    """Users should be able to create a subscription with entitlement configs."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription with entitlements
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "is_active": False,
            "entitlements": [
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "organization",
                    "config": {"max_storage": 5000000000},
                },
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "user",
                    "config": {"max_storage": 1000000000},
                },
            ],
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.json()

    # Check entitlements were created
    assert len(data["entitlements"]) == 2
    org_entitlement = next(
        e for e in data["entitlements"] if e["account_type"] == "organization"
    )
    user_entitlement = next(
        e for e in data["entitlements"] if e["account_type"] == "user"
    )
    assert org_entitlement["config"]["max_storage"] == 5000000000
    assert user_entitlement["config"]["max_storage"] == 1000000000


def test_api_subscription_update_with_entitlements():
    """Users should be able to update a subscription with entitlement configs."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription first
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    # Create an initial entitlement
    factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="organization",
        config={"max_storage": 1000},
    )

    # Update subscription with new entitlement config
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "entitlements": [
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "organization",
                    "config": {"max_storage": 9999},
                },
            ],
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()

    # Check entitlement was updated
    assert len(data["entitlements"]) == 1
    assert data["entitlements"][0]["config"]["max_storage"] == 9999


def test_api_subscription_entitlements_does_not_override_account_specific():
    """Entitlements input should not override account-specific entitlements."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription with account-specific entitlement
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    account = factories.AccountFactory(organization=organization, type="user")
    account_entitlement = factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="user",
        account=account,
        config={"max_storage": 999},
    )

    # Update subscription with default entitlement config
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "entitlements": [
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "user",
                    "config": {"max_storage": 5000},
                },
            ],
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()

    # Should have 2 entitlements now: the account-specific one and the new default one
    assert len(data["entitlements"]) == 2

    # Account-specific entitlement should be unchanged
    account_ent = next(
        e for e in data["entitlements"] if e["account"] == str(account.id)
    )
    assert account_ent["config"]["max_storage"] == 999

    # Default entitlement should have been created
    default_ent = next(e for e in data["entitlements"] if e["account"] is None)
    assert default_ent["config"]["max_storage"] == 5000

    # Verify in DB
    account_entitlement.refresh_from_db()
    assert account_entitlement.config["max_storage"] == 999


def test_api_subscription_with_empty_entitlements_array():
    """Sending an empty entitlements array should not change existing entitlements."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription with an entitlement
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="organization",
        config={"max_storage": 1000},
    )

    # Update subscription with empty entitlements array
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "entitlements": [],
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()

    # Existing entitlement should be unchanged
    assert len(data["entitlements"]) == 1
    assert data["entitlements"][0]["config"]["max_storage"] == 1000


def test_api_subscription_without_entitlements_key():
    """Sending a request without the entitlements key should not change existing entitlements."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription with an entitlement
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="organization",
        config={"max_storage": 1000},
    )

    # Update subscription without entitlements key
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()

    # Existing entitlement should be unchanged
    assert len(data["entitlements"]) == 1
    assert data["entitlements"][0]["config"]["max_storage"] == 1000


def test_api_subscription_with_duplicate_entitlements():
    """Sending duplicate entitlements (same type+account_type) should use the last value."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription with duplicate entitlements in request
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "is_active": False,
            "entitlements": [
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "organization",
                    "config": {"max_storage": 1000},
                },
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "organization",
                    "config": {"max_storage": 9999},  # Last one should win
                },
            ],
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.json()

    # Should only have one entitlement with the last value
    assert len(data["entitlements"]) == 1
    assert data["entitlements"][0]["config"]["max_storage"] == 9999


def test_api_subscription_with_unknown_entitlement_type():
    """Sending an unknown entitlement type should be rejected."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory()

    # Create subscription with unknown entitlement type
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "is_active": False,
            "entitlements": [
                {
                    "type": "totally_made_up_type",
                    "account_type": "organization",
                    "config": {"some_key": "some_value"},
                },
            ],
        },
        format="json",
    )
    # Unknown entitlement types are rejected at the serializer level
    assert response.status_code == 400
    data = response.json()
    assert "type" in str(data).lower() or "entitlement" in str(data).lower()


def test_api_subscription_with_wrong_service_entitlement_type():
    """Sending an entitlement type that doesn't match the service should be rejected."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    # Create a messages service
    service = factories.ServiceFactory(type="messages")

    # Try to create subscription with drive_storage entitlement (wrong for messages)
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {
            "is_active": False,
            "entitlements": [
                {
                    "type": models.Entitlement.EntitlementType.DRIVE_STORAGE,
                    "account_type": "organization",
                    "config": {"max_storage": 1000000},
                },
            ],
        },
        format="json",
    )
    # Should be rejected because drive_storage is not valid for messages service
    assert response.status_code == 400
    data = response.json()
    assert "not valid" in str(data).lower() or "entitlement" in str(data).lower()
