# pylint: disable=invalid-name
"""
Test entitlements messages API endpoints in the deploycenter core app.
"""

import pytest
import responses
from responses import matchers
from rest_framework.test import APIClient

from core import factories, models
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db

# pylint: disable=assignment-from-none
# pylint: disable=duplicate-code


@pytest.mark.django_db()
def test_subscription_entitlements_default():
    """When a messages service subscription is created, a default messages storage entitlement should be created."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="messages")

    # Assert that the entitlement does not exist before subscription creation
    assert not models.Entitlement.objects.exists()

    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    assert models.Entitlement.objects.count() == 2

    entitlement_user = models.Entitlement.objects.get(
        service_subscription__organization=organization,
        service_subscription__service=service,
        service_subscription__operator=operator,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="user",
        account_id="",
    )
    assert entitlement_user.config["max_storage"] == 1000 * 1000 * 1000 * 5

    entitlement_organization = models.Entitlement.objects.get(
        service_subscription__organization=organization,
        service_subscription__service=service,
        service_subscription__operator=operator,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account_id="",
    )
    assert entitlement_organization.config["max_storage"] == 1000 * 1000 * 1000 * 50


@pytest.mark.django_db()
@responses.activate
def test_api_entitlements_user_can_store():
    """Test the can_store entitlement for a user entitlement."""
    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {"account_type": "user", "account_id": "xyz", "limit": 1000, "offset": 0}
    response_mock = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": 500},
                }
            ],
        },
        status=200,
    )

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="user",
        account_id="",
        config={
            "max_storage": 1000,
        },
    )

    # Test that we can store messages
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_store": True,
                "can_store_resolve_level": "user",
            },
        },
    )

    # Metrics should be stored in the database
    metrics = models.Metric.objects.filter(service=service, organization=organization)
    assert metrics.count() == 1
    assert metrics.first().value == 500
    assert metrics.first().key == "storage_used"
    assert metrics.first().account_type == "user"
    assert metrics.first().account_id == "xyz"
    assert metrics.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock.call_count == 1
    assert (
        response_mock.calls[0].request.headers["Authorization"] == "Bearer test_token"
    )

    # Simulate storage used exceeding the max storage size
    response_mock = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": 1001},
                }
            ],
        },
        status=200,
    )

    # Test that we cannot upload more than the max storage size
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_store": False,
                "can_store_resolve_level": "user",
            },
        },
    )

    # Metrics should be stored in the database
    metrics = models.Metric.objects.filter(service=service, organization=organization)
    assert metrics.count() == 1
    assert metrics.first().value == 1001
    assert metrics.first().key == "storage_used"
    assert metrics.first().account_type == "user"
    assert metrics.first().account_id == "xyz"
    assert metrics.first().organization == organization


@pytest.mark.django_db()
@responses.activate
@pytest.mark.parametrize(
    "organization_storage_used,user_storage_used,can_store,resolve_level",
    [
        (5000, 500, True, "user"),  # User and organization have free space left
        (
            5000,
            1001,
            False,
            "user",
        ),  # User has no free space left, organization has free space left
        (
            10001,
            500,
            False,
            "organization",
        ),  # User has free space left, organization has no free space left
        (
            10001,
            1001,
            False,
            "organization",
        ),  # User and organization have no free space left
    ],
)
def test_api_entitlements_organization_can_store(
    organization_storage_used, user_storage_used, can_store, resolve_level
):
    """Test the can_store entitlement for an organization and user entitlement."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")

    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params_user = {
        "account_type": "user",
        "account_id": "xyz",
        "limit": 1000,
        "offset": 0,
    }
    response_mock_user = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params_user)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": user_storage_used},
                }
            ],
        },
        status=200,
    )
    params_organization = {
        "account_type": "organization",
        "account_id": str(organization.id),
        "limit": 1000,
        "offset": 0,
    }
    response_mock_organization = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params_organization)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "organization",
                        "id": str(organization.id),
                    },
                    "metrics": {"storage_used": organization_storage_used},
                }
            ],
        },
        status=200,
    )

    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account_id="",
        config={
            "max_storage": 10000,
        },
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="user",
        account_id="",
        config={
            "max_storage": 1000,
        },
    )

    # Test that we can store messages
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_store": can_store,
                "can_store_resolve_level": resolve_level,
            },
        },
    )

    # Check the number of created metrics for this subscription.
    assert (
        models.Metric.objects.filter(service=service, organization=organization).count()
        == 2
    )

    # Metrics should be stored in the database for the user
    metrics_user = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account_type="user",
        account_id="xyz",
    )
    assert metrics_user.count() == 1
    assert metrics_user.first().value == user_storage_used
    assert metrics_user.first().key == "storage_used"
    assert metrics_user.first().account_type == "user"
    assert metrics_user.first().account_id == "xyz"
    assert metrics_user.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_user.call_count == 1
    assert (
        response_mock_user.calls[0].request.headers["Authorization"]
        == "Bearer test_token"
    )

    # Metrics should be stored in the database for the organization
    metrics_organization = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account_type="organization",
        account_id=organization.id,
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == organization_storage_used
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account_type == "organization"
    assert metrics_organization.first().account_id == str(organization.id)
    assert metrics_organization.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_organization.call_count == 1
    assert (
        response_mock_organization.calls[0].request.headers["Authorization"]
        == "Bearer test_token"
    )


@pytest.mark.django_db()
@responses.activate
@pytest.mark.parametrize(
    "override_max_storage,user_storage_used,can_store_before_override,can_store",
    [
        (1000, 800, False, True),  # Override by higher max storage.
        (300, 400, True, False),  # Override by lower max storage.
    ],
)
def test_api_entitlements_user_override_can_store(
    override_max_storage, user_storage_used, can_store_before_override, can_store
):
    """Test the can_store entitlement with a user override."""

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")

    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {"account_type": "user", "account_id": "xyz", "limit": 1000, "offset": 0}
    response_mock = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": user_storage_used},
                }
            ],
        },
        status=200,
    )

    params_organization = {
        "account_type": "organization",
        "account_id": str(organization.id),
        "limit": 1000,
        "offset": 0,
    }
    response_mock_organization = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params_organization)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "organization",
                        "id": str(organization.id),
                    },
                    "metrics": {"storage_used": 800},
                }
            ],
        },
        status=200,
    )

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account_id="",
        config={
            "max_storage": 1000,
        },
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="user",
        account_id="",
        config={
            "max_storage": 500,
        },
    )

    # Test that we can store messages
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_store": can_store_before_override,
            },
        },
    )

    # Create a new entitlement as user override.
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="user",
        account_id="xyz",
        config={
            "max_storage": override_max_storage,
        },
    )

    # Test that now the user can store messages because of the user override.
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_store": can_store,
                "can_store_resolve_level": "user_override",
            },
        },
    )

    # Check the number of created metrics for this subscription.
    assert (
        models.Metric.objects.filter(service=service, organization=organization).count()
        == 2
    )

    # Metrics should be stored in the database for the user
    metrics_user = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account_type="user",
        account_id="xyz",
    )
    assert metrics_user.count() == 1
    assert metrics_user.first().value == user_storage_used
    assert metrics_user.first().key == "storage_used"
    assert metrics_user.first().account_type == "user"
    assert metrics_user.first().account_id == "xyz"
    assert metrics_user.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock.call_count == 2

    # Metrics should be stored in the database for the organization
    metrics_organization = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account_type="organization",
        account_id=organization.id,
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == 800
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account_type == "organization"
    assert metrics_organization.first().account_id == str(organization.id)
    assert metrics_organization.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_organization.call_count == 2


@pytest.mark.parametrize(
    "entitlement_config,storage_used",
    [
        ({"max_storage": 0}, 1000000),  # Explicitly set to 0
        ({}, 5000000),  # Missing max_storage key - should default to 0
    ],
)
@responses.activate
def test_api_entitlements_list_unlimited_storage(entitlement_config, storage_used):
    """
    Test that when max_storage is 0 or missing, can_upload is always True (unlimited storage).
    """
    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {"account_type": "user", "account_id": "xyz", "limit": 1000, "offset": 0}
    responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": storage_used},
                }
            ],
        },
        status=200,
    )

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        config=entitlement_config,
        account_type="user",
        account_id="",
    )

    # Test that can_store is True even with high storage usage
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_store": True,  # Should be True even with high usage when max_storage is 0 or missing
                "can_store_resolve_level": "user",
            },
        },
    )
