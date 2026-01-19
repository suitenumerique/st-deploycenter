"""
Test entitlements admin API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db

# pylint: disable=unused-argument


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_is_admin_false_no_account(
    account_key, account_key_value, account_key_http_alias
):
    """Test the is_admin entitlement for a user entitlement."""

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
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "is_admin": False,
                "is_admin_reason": "no_account",
            },
        },
    )


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_is_admin_false_no_admin_role(
    account_key, account_key_value, account_key_http_alias
):
    """Test the is_admin entitlement for a user entitlement."""

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
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        **{account_key: account_key_value},
        roles=[],
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
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "is_admin": False,
                "is_admin_reason": "no_admin_role",
            },
        },
    )


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_is_admin_true_organization_level(
    account_key, account_key_value, account_key_http_alias
):
    """Test the is_admin entitlement for a user entitlement."""

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
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        **{account_key: account_key_value},
        roles=["admin"],
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
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "is_admin": True,
                "is_admin_resolve_level": "organization",
            },
        },
    )


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "test@example.com", "email"]],
)
def test_api_entitlements_is_admin_true_service_level(
    account_key, account_key_value, account_key_http_alias
):
    """Test the is_admin entitlement for a user entitlement."""

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
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    account = factories.AccountFactory(
        organization=organization,
        type="user",
        roles=[],
        **{account_key: account_key_value},
    )

    account.service_links.create(service=service, roles=["admin"])

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
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "is_admin": True,
                "is_admin_resolve_level": "service",
            },
        },
    )
