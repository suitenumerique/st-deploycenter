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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "is_admin": False,
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
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "is_admin": False,
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

    account.service_links.create(service=service, role="admin")

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
                "is_admin": True,
                "is_admin_resolve_level": "service",
            },
        },
    )


# --- Operator admin passthrough (base resolver) ---


def _make_service(**extra_config):
    config = {"entitlements_api_key": "test_token"}
    config.update(extra_config)
    return factories.ServiceFactory(config=config)


def _entitlements_by_email(client, service, siret, account_email):
    return client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_email": account_email,
            "siret": siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )


def test_operator_admin_passthrough_is_admin_true():
    """Operator admin gets is_admin=True with resolve_level=operator."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_service()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    response = _entitlements_by_email(
        client, service, organization.siret, "admin@operator.fr"
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "entitlements": {
                "can_access": True,
                "is_admin": True,
                "is_admin_resolve_level": "operator",
            },
        },
    )


def test_operator_admin_passthrough_flag_off_is_admin_false():
    """Flag off → operator admin does not get is_admin."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = _make_service()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    response = _entitlements_by_email(
        client, service, organization.siret, "admin@operator.fr"
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "entitlements": {
                "is_admin": False,
            },
        },
    )


def test_operator_admin_passthrough_works_for_extended_admin():
    """Operator admin passthrough works for ADC/ESD services (ExtendedAdminEntitlementResolver)."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(
        siret="12345678900001", population=50000
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_service(type="adc")
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"auto_admin": "manual"},
    )

    response = _entitlements_by_email(
        client, service, organization.siret, "admin@operator.fr"
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "entitlements": {
                "can_access": True,
                "is_admin": True,
                "is_admin_resolve_level": "operator",
            },
        },
    )


def test_operator_admin_passthrough_no_account_still_works():
    """Operator admin gets is_admin even when no Account exists for the email."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_service()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # No Account created for admin@operator.fr
    response = _entitlements_by_email(
        client, service, organization.siret, "admin@operator.fr"
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "entitlements": {
                "is_admin": True,
                "is_admin_resolve_level": "operator",
            },
        },
    )
