# pylint: disable=invalid-name
"""
Test entitlements messages API endpoints in the deploycenter core app.
"""

import pytest
import responses
from responses import matchers
from rest_framework.test import APIClient

from core import factories, models

pytestmark = pytest.mark.django_db

# pylint: disable=assignment-from-none
# pylint: disable=duplicate-code
# pylint: disable=unused-argument


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

    entitlement_mailbox = models.Entitlement.objects.get(
        service_subscription__organization=organization,
        service_subscription__service=service,
        service_subscription__operator=operator,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="mailbox",
        account=None,
    )
    assert entitlement_mailbox.config["max_storage"] == 1000 * 1000 * 1000 * 5

    entitlement_organization = models.Entitlement.objects.get(
        service_subscription__organization=organization,
        service_subscription__service=service,
        service_subscription__operator=operator,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account=None,
    )
    assert entitlement_organization.config["max_storage"] == 1000 * 1000 * 1000 * 50


@responses.activate
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_mailbox_can_store(
    account_key, account_key_value, account_key_http_alias
):
    """Test the can_store entitlement for a mailbox entitlement."""
    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "mailbox",
        f"account_{account_key_http_alias}": account_key_value,
        "limit": 1000,
        "offset": 0,
    }
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
                        "type": "mailbox",
                        "id": "xyz",
                        "email": "test@example.com",
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
        type="messages",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    models.Entitlement.objects.all().delete()
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="mailbox",
        account=None,
        config={
            "max_storage": 1000,
        },
    )

    # Test that we can store messages
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "mailbox",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": True,
            "can_store_resolve_level": "mailbox",
            "max_storage": 1000,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": 500,
        },
    }

    # Metrics should be stored in the database
    metrics = models.Metric.objects.filter(service=service, organization=organization)
    assert metrics.count() == 1
    assert metrics.first().value == 500
    assert metrics.first().key == "storage_used"
    assert metrics.first().account.type == "mailbox"
    assert metrics.first().account.external_id == "xyz"
    assert metrics.first().account.email == "test@example.com"
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
                        "type": "mailbox",
                        "id": "xyz",
                        "email": "test@example.com",
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
            "account_type": "mailbox",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": False,
            "can_store_resolve_level": "mailbox",
            "max_storage": 1000,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": 1001,
        },
    }

    # Metrics should be stored in the database
    metrics = models.Metric.objects.filter(service=service, organization=organization)
    assert metrics.count() == 1
    assert metrics.first().value == 1001
    assert metrics.first().key == "storage_used"
    assert metrics.first().account.type == "mailbox"
    assert metrics.first().account.external_id == "xyz"
    assert metrics.first().account.email == "test@example.com"
    assert metrics.first().organization == organization


@responses.activate
@pytest.mark.parametrize(
    "organization_storage_used,mailbox_storage_used,can_store,resolve_level",
    [
        (5000, 500, True, "mailbox"),  # Mailbox and organization have free space left
        (
            5000,
            1001,
            False,
            "mailbox",
        ),  # Mailbox has no free space left, organization has free space left
        (
            10001,
            500,
            False,
            "organization",
        ),  # Mailbox has free space left, organization has no free space left
        (
            10001,
            1001,
            False,
            "organization",
        ),  # Mailbox and organization have no free space left
    ],
)
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_organization_can_store(
    organization_storage_used,
    mailbox_storage_used,
    can_store,
    resolve_level,
    account_key,
    account_key_value,
    account_key_http_alias,
):
    """Test the can_store entitlement for an organization and mailbox entitlement."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")

    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params_mailbox = {
        "account_type": "mailbox",
        f"account_{account_key_http_alias}": account_key_value,
        "limit": 1000,
        "offset": 0,
    }
    response_mock_mailbox = responses.add(
        responses.GET,
        metrics_usage_endpoint,
        match=[matchers.query_param_matcher(params_mailbox)],
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "mailbox",
                        "id": "xyz",
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": mailbox_storage_used},
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
                        "email": "test@example.com",
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
        type="messages",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    models.Entitlement.objects.all().delete()
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account=None,
        config={
            "max_storage": 10000,
        },
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="mailbox",
        account=None,
        config={
            "max_storage": 1000,
        },
    )

    # Test that we can store messages
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "mailbox",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    expected_max_storage = 10000 if resolve_level == "organization" else 1000
    expected_storage_used = (
        organization_storage_used
        if resolve_level == "organization"
        else mailbox_storage_used
    )
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": can_store,
            "can_store_resolve_level": resolve_level,
            "max_storage": expected_max_storage,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": expected_storage_used,
        },
    }

    # Check the number of created metrics for this subscription.
    assert (
        models.Metric.objects.filter(service=service, organization=organization).count()
        == 2
    )

    # Metrics should be stored in the database for the mailbox
    metrics_mailbox = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="mailbox",
        **{f"account__{account_key}": account_key_value},
    )
    assert metrics_mailbox.count() == 1
    assert metrics_mailbox.first().value == mailbox_storage_used
    assert metrics_mailbox.first().key == "storage_used"
    assert metrics_mailbox.first().account.type == "mailbox"
    assert metrics_mailbox.first().account.external_id == "xyz"
    assert metrics_mailbox.first().account.email == "test@example.com"
    assert metrics_mailbox.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_mailbox.call_count == 1
    assert (
        response_mock_mailbox.calls[0].request.headers["Authorization"]
        == "Bearer test_token"
    )

    # Metrics should be stored in the database for the organization
    metrics_organization = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="organization",
        account__external_id=str(organization.id),
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == organization_storage_used
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account.type == "organization"
    assert metrics_organization.first().account.external_id == str(organization.id)
    assert metrics_organization.first().account.email == "test@example.com"
    assert metrics_organization.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_organization.call_count == 1
    assert (
        response_mock_organization.calls[0].request.headers["Authorization"]
        == "Bearer test_token"
    )


@responses.activate
@pytest.mark.parametrize(
    "override_max_storage,mailbox_storage_used,can_store_before_override,can_store",
    [
        (1000, 800, False, True),  # Override by higher max storage.
        (300, 400, True, False),  # Override by lower max storage.
    ],
)
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_mailbox_override_can_store(
    override_max_storage,
    mailbox_storage_used,
    can_store_before_override,
    can_store,
    account_key,
    account_key_value,
    account_key_http_alias,
):
    """Test the can_store entitlement with a mailbox override."""

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")

    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "mailbox",
        f"account_{account_key_http_alias}": account_key_value,
        "limit": 1000,
        "offset": 0,
    }
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
                        "type": "mailbox",
                        "id": "xyz",
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": mailbox_storage_used},
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
        type="messages",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    models.Entitlement.objects.all().delete()
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="organization",
        account=None,
        config={
            "max_storage": 1000,
        },
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="mailbox",
        account=None,
        config={
            "max_storage": 500,
        },
    )

    # Test that we can store messages
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "mailbox",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": can_store_before_override,
            "can_store_resolve_level": "mailbox",
            "max_storage": 500,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": mailbox_storage_used,
        },
    }

    # Create a new entitlement as mailbox override.
    account = models.Account.objects.get(
        external_id="xyz", type="mailbox", organization=organization
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        account_type="mailbox",
        account=account,
        config={
            "max_storage": override_max_storage,
        },
    )

    # Test that now the mailbox can store messages because of the mailbox override.
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "mailbox",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": can_store,
            "can_store_resolve_level": "mailbox_override",
            "max_storage": override_max_storage,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": mailbox_storage_used,
        },
    }

    # Check the number of created metrics for this subscription.
    assert (
        models.Metric.objects.filter(service=service, organization=organization).count()
        == 2
    )

    # Metrics should be stored in the database for the mailbox
    metrics_mailbox = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="mailbox",
        **{f"account__{account_key}": account_key_value},
    )
    assert metrics_mailbox.count() == 1
    assert metrics_mailbox.first().value == mailbox_storage_used
    assert metrics_mailbox.first().key == "storage_used"
    assert metrics_mailbox.first().account.type == "mailbox"
    assert metrics_mailbox.first().account.external_id == "xyz"
    assert metrics_mailbox.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock.call_count == 2

    # Metrics should be stored in the database for the organization
    metrics_organization = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="organization",
        account__external_id=str(organization.id),
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == 800
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account.type == "organization"
    assert metrics_organization.first().account.external_id == str(organization.id)
    assert metrics_organization.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_organization.call_count == 2

    # Make sure another account is not affected by the override.
    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "mailbox",
        "account_id": "abc",
        "limit": 1000,
        "offset": 0,
    }
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
                        "type": "mailbox",
                        "id": "abc",
                        "email": "abc@example.com",
                    },
                    "metrics": {"storage_used": mailbox_storage_used},
                }
            ],
        },
        status=200,
    )
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "mailbox",
            "account_id": "abc",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": can_store_before_override,
            "can_store_resolve_level": "mailbox",
            "max_storage": 500,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": mailbox_storage_used,
        },
    }
    metrics_mailbox = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="mailbox",
    )
    assert metrics_mailbox.count() == 2
    assert response_mock.call_count == 1


@pytest.mark.parametrize(
    "entitlement_config,storage_used",
    [
        ({"max_storage": 0}, 1000000),  # Explicitly set to 0
        ({}, 5000000),  # Missing max_storage key - should default to 0
    ],
)
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
@responses.activate
def test_api_entitlements_list_unlimited_storage(
    entitlement_config,
    storage_used,
    account_key,
    account_key_value,
    account_key_http_alias,
):
    """
    Test that when max_storage is 0 or missing, can_upload is always True (unlimited storage).
    """
    metrics_usage_endpoint = "https://messages.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "mailbox",
        f"account_{account_key_http_alias}": account_key_value,
        "limit": 1000,
        "offset": 0,
    }
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
                        "type": "mailbox",
                        "id": "xyz",
                        "email": "test@example.com",
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
        type="messages",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    models.Entitlement.objects.all().delete()
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        config=entitlement_config,
        account_type="mailbox",
        account=None,
    )

    # Test that can_store is True even with high storage usage
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "mailbox",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
            "can_store": True,
            "can_store_resolve_level": "mailbox",
            "max_storage": 0,
            "can_admin_maildomains": [],
        },
        "metrics": {
            "storage_used": storage_used,
        },
    }
