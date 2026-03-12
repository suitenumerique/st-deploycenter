# pylint: disable=invalid-name
"""
Test entitlements drive API endpoints in the deploycenter core app.
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
# pylint: disable=unused-argument


def test_subscription_entitlements_default():
    """When a drive service subscription is created, a default drive storage entitlement should be created."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="drive")

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
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="user",
        account=None,
    )
    assert entitlement_user.config["max_storage"] == 1000 * 1000 * 1000 * 5

    entitlement_organization = models.Entitlement.objects.get(
        service_subscription__organization=organization,
        service_subscription__service=service,
        service_subscription__operator=operator,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="organization",
        account=None,
    )
    assert entitlement_organization.config["max_storage"] == 1000 * 1000 * 1000 * 10


@pytest.mark.django_db()
@responses.activate
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias,metrics_param_key",
    [
        ["external_id", "xyz", "id", "account_id_value"],
        ["email", "test@example.com", "email", "account_email"],
    ],
)
def test_api_entitlements_can_access_without_subscription(
    account_key, account_key_value, account_key_http_alias, metrics_param_key
):
    """
    Test the can_access entitlement for a user entitlement without a subscription.
    Even without subscription, the user should be able to access the service but without
    any entitlement. ( Especially can_upload )
    """
    metrics_usage_endpoint = "https://fichiers.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "user",
        metrics_param_key: account_key_value,
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
                        "type": "user",
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
        type="drive",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )

    # Test that we can access the service without a subscription but without any entitlement.
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": {
            "type": organization.type,
            "name": organization.name,
            "oidc_valid": None,
        },
        "operator": None,
        "entitlements": {
            "can_access": True,
        },
    }

    # Create an inactive subscription to test that the user can still access the service.
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=False,
    )
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": {
            "type": organization.type,
            "name": organization.name,
            "oidc_valid": None,
        },
        "operator": None,
        "entitlements": {
            "can_access": True,
        },
    }


@pytest.mark.django_db()
@responses.activate
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias,metrics_param_key",
    [
        ["external_id", "xyz", "id", "account_id_value"],
        ["email", "test@example.com", "email", "account_email"],
    ],
)
def test_api_entitlements_user_can_upload(
    account_key, account_key_value, account_key_http_alias, metrics_param_key
):
    """Test the can_upload entitlement for a user entitlement."""

    organization = factories.OrganizationFactory(siret="12345678900001")
    metrics_usage_endpoint = "https://fichiers.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "user",
        metrics_param_key: account_key_value,
        "limit": 1000,
        "offset": 0,
    }
    response_mock_user = responses.add(
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
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": 500},
                }
            ],
        },
        status=200,
    )
    params_organization = {
        "account_type": "organization",
        "account_id_key": "siret",
        "account_id_value": organization.siret,
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
                    },
                    "metrics": {"storage_used": 1000},
                }
            ],
        },
        status=200,
    )

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="drive",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # Test that we can upload to the drive
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": True,
                "can_upload_resolve_level": "user",
            },
        },
    )

    # Metrics should be stored in the database
    metrics_user = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="user",
        account__external_id="xyz",
    )
    assert metrics_user.count() == 1
    assert metrics_user.first().value == 500
    assert metrics_user.first().key == "storage_used"
    assert metrics_user.first().account.type == "user"
    assert metrics_user.first().account.external_id == "xyz"
    assert metrics_user.first().account.email == "test@example.com"
    assert metrics_user.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_user.call_count == 1
    assert (
        response_mock_user.calls[0].request.headers["Authorization"]
        == "Bearer test_token"
    )

    metrics_organization = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="organization",
        account__external_id=organization.siret,
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == 1000
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account.type == "organization"
    assert metrics_organization.first().account.external_id == organization.siret
    assert metrics_organization.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock_organization.call_count == 1
    assert (
        response_mock_organization.calls[0].request.headers["Authorization"]
        == "Bearer test_token"
    )

    # Simulate storage used exceeding the max storage size
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
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": 1000 * 1000 * 1000 * 50 + 1},
                }
            ],
        },
        status=200,
    )
    responses.add(
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
                    },
                    "metrics": {"storage_used": 1000 * 1000 * 1000 * 50 + 1},
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
            f"account_{account_key_http_alias}": account_key_value,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_upload": False,
                "can_access": True,
            },
        },
    )

    # Metrics should be stored in the database
    metrics_user = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="user",
        account__external_id="xyz",
    )
    assert metrics_user.count() == 1
    assert metrics_user.first().value == 1000 * 1000 * 1000 * 50 + 1
    assert metrics_user.first().key == "storage_used"
    assert metrics_user.first().account.type == "user"
    assert metrics_user.first().account.external_id == "xyz"
    assert metrics_user.first().organization == organization

    # Metrics should be stored in the database for the organization
    metrics_organization = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type="organization",
        account__external_id=organization.siret,
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == 1000 * 1000 * 1000 * 50 + 1
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account.type == "organization"
    assert metrics_organization.first().account.external_id == organization.siret
    assert metrics_organization.first().organization == organization


@pytest.mark.django_db()
@responses.activate
@pytest.mark.parametrize(
    "organization_storage_used,user_storage_used,can_upload,resolve_level",
    [
        (
            5000,
            500,
            True,
            "user",
        ),  # User and organization have free space left
        (
            5000,
            1000 * 1000 * 1000 * 10 + 1,
            False,
            "user",
        ),  # User has no free space left, organization has free space left
        (
            1000 * 1000 * 1000 * 50 + 1,
            500,
            False,
            "organization",
        ),  # User has free space left, organization has no free space left
        (
            1000 * 1000 * 1000 * 50 + 1,
            1000 * 1000 * 1000 * 10 + 1,
            False,
            "organization",
        ),  # User and organization have no free space left
    ],
)
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias,metrics_param_key",
    [
        ["external_id", "xyz", "id", "account_id_value"],
        ["email", "test@example.com", "email", "account_email"],
    ],
)
def test_api_entitlements_organization_can_upload(
    organization_storage_used,
    user_storage_used,
    can_upload,
    resolve_level,
    account_key,
    account_key_value,
    account_key_http_alias,
    metrics_param_key,
):
    """Test the can_upload entitlement for an organization and user entitlement."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")

    metrics_usage_endpoint = "https://fichiers.suite.anct.gouv.fr/metrics/usage"
    params_user = {
        "account_type": "user",
        metrics_param_key: account_key_value,
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
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": user_storage_used},
                }
            ],
        },
        status=200,
    )
    params_organization = {
        "account_type": "organization",
        "account_id_key": "siret",
        "account_id_value": organization.siret,
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
        type="drive",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # Test that we can upload to the drive
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": can_upload,
                "can_upload_resolve_level": resolve_level,
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
        account__type="user",
        **{f"account__{account_key}": account_key_value},
    )
    assert metrics_user.count() == 1
    assert metrics_user.first().value == user_storage_used
    assert metrics_user.first().key == "storage_used"
    assert metrics_user.first().account.type == "user"
    assert metrics_user.first().account.external_id == "xyz"
    assert metrics_user.first().account.email == "test@example.com"
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
        account__type="organization",
        account__external_id=organization.siret,
    )
    assert metrics_organization.count() == 1
    assert metrics_organization.first().value == organization_storage_used
    assert metrics_organization.first().key == "storage_used"
    assert metrics_organization.first().account.type == "organization"
    assert metrics_organization.first().account.external_id == organization.siret
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
    "override_max_storage,user_storage_used,can_upload_before_override,can_upload",
    [
        (1000, 800, False, True),  # Override by higher max storage.
        (300, 400, True, False),  # Override by lower max storage.
    ],
)
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias,metrics_param_key",
    [
        ["external_id", "xyz", "id", "account_id_value"],
        ["email", "test@example.com", "email", "account_email"],
    ],
)
def test_api_entitlements_user_override_can_upload(
    override_max_storage,
    user_storage_used,
    can_upload_before_override,
    can_upload,
    account_key,
    account_key_value,
    account_key_http_alias,
    metrics_param_key,
):
    """Test the can_upload entitlement with a user override."""
    metrics_usage_endpoint = "https://fichiers.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "user",
        metrics_param_key: account_key_value,
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
                        "type": "user",
                        "id": "xyz",
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": user_storage_used},
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
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="user",
        account=None,
        config={
            "max_storage": 500,
        },
    )

    # Test that we can upload to the drive
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": can_upload_before_override,
                "can_upload_resolve_level": "user",
            },
        },
    )

    # Create a new entitlement as user override.
    # Get the account created from metrics scraping.
    account = models.Account.objects.get(
        external_id="xyz", type="user", organization=organization
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="user",
        account=account,
        config={
            "max_storage": override_max_storage,
        },
    )

    # Test that now the user can upload because of the user override.
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": can_upload,
                "can_upload_resolve_level": "user_override",
            },
        },
    )

    # Metrics should be stored in the database
    metrics = models.Metric.objects.filter(service=service, organization=organization)
    assert metrics.count() == 1
    assert metrics.first().value == user_storage_used
    assert metrics.first().key == "storage_used"
    assert metrics.first().account.type == "user"
    assert metrics.first().account.external_id == "xyz"
    assert metrics.first().account.email == "test@example.com"
    assert metrics.first().organization == organization

    # Metrics endpoint should have been called
    assert response_mock.call_count == 2

    # Make sure another account is not affected by the override.
    params = {"account_type": "user", "account_id_value": "abc", "limit": 1000, "offset": 0}
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
                        "id": "abc",
                        "email": "abc@example.com",
                    },
                    "metrics": {"storage_used": user_storage_used},
                }
            ],
        },
        status=200,
    )
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "abc",
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": can_upload_before_override,
                "can_upload_resolve_level": "user",
            },
        },
    )

    assert metrics.count() == 2
    assert response_mock.call_count == 1


@pytest.mark.parametrize(
    "entitlement_config,storage_used",
    [
        ({"max_storage": 0}, 1000000),  # Explicitly set to 0
        ({}, 5000000),  # Missing max_storage key - should default to 0
    ],
)
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias,metrics_param_key",
    [
        ["external_id", "xyz", "id", "account_id_value"],
        ["email", "test@example.com", "email", "account_email"],
    ],
)
@responses.activate
def test_api_entitlements_list_unlimited_storage(
    entitlement_config,
    storage_used,
    account_key,
    account_key_value,
    account_key_http_alias,
    metrics_param_key,
):
    """
    Test that when max_storage is 0 or missing, can_upload is always True (unlimited storage).
    """
    metrics_usage_endpoint = "https://fichiers.suite.anct.gouv.fr/metrics/usage"
    params = {
        "account_type": "user",
        metrics_param_key: account_key_value,
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
                        "type": "user",
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
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config=entitlement_config,
        account_type="user",
        account=None,
    )

    # Test that can_upload is True even with high storage usage
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            f"account_{account_key_http_alias}": account_key_value,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": True,  # Should be True even with high usage when max_storage is 0 or missing
                "can_upload_resolve_level": "user",
            },
        },
    )
