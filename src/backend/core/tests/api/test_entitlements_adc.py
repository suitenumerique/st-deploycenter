# pylint: disable=invalid-name
"""
Test ADC-specific admin entitlements in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db

# pylint: disable=unused-argument


@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "contact@mairie.fr", "email"]],
)
def test_api_entitlements_is_admin_email_contact(
    account_key, account_key_value, account_key_http_alias
):
    """Test is_admin is True when account email matches organization's adresse_messagerie."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # Create account with the matching email
    account_kwargs = {
        "organization": organization,
        "type": "user",
        account_key: account_key_value,
    }
    if account_key != "email":
        account_kwargs["email"] = "contact@mairie.fr"
    factories.AccountFactory(**account_kwargs)

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
                "is_admin_resolve_level": "email_contact",
            },
        },
    )


@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "other@example.com", "email"]],
)
def test_api_entitlements_is_admin_false_no_match(
    account_key, account_key_value, account_key_http_alias
):
    """Test is_admin is False when email does not match and population >= threshold."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    account_kwargs = {
        "organization": organization,
        "type": "user",
        account_key: account_key_value,
    }
    if account_key != "email":
        account_kwargs["email"] = "other@example.com"
    factories.AccountFactory(**account_kwargs)

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
    assert data["entitlements"]["is_admin"] is False


@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "other@example.com", "email"]],
)
def test_api_entitlements_is_admin_population_under_threshold(
    account_key, account_key_value, account_key_http_alias
):
    """Test is_admin is True when population < threshold, even without email match."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=2000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    account_kwargs = {
        "organization": organization,
        "type": "user",
        account_key: account_key_value,
    }
    if account_key != "email":
        account_kwargs["email"] = "someone.else@example.com"
    factories.AccountFactory(**account_kwargs)

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "population"


@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "other@example.com", "email"]],
)
@pytest.mark.parametrize(
    "population,expected_admin",
    [
        (3499, True),  # Under threshold -> admin
        (3500, False),  # At threshold -> not admin
        (3501, False),  # Over threshold -> not admin
        (100, True),  # Well under -> admin
        (10000, False),  # Well over -> not admin
        (None, False),  # Unknown population -> not admin
    ],
)
def test_api_entitlements_is_admin_population_boundary(
    account_key, account_key_value, account_key_http_alias, population, expected_admin
):
    """Test population threshold boundary values for is_admin (no email match)."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=population,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # Email does NOT match adresse_messagerie, so only population check applies
    account_kwargs = {
        "organization": organization,
        "type": "user",
        account_key: account_key_value,
    }
    if account_key != "email":
        account_kwargs["email"] = "someone@example.com"
    factories.AccountFactory(**account_kwargs)

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
    assert data["entitlements"]["is_admin"] is expected_admin


def test_api_entitlements_is_admin_case_insensitive_email():
    """Test that email matching against adresse_messagerie is case-insensitive."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="Contact@Mairie.FR",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        email="contact@mairie.fr",
        external_id="xyz",
    )

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "email_contact"


def test_api_entitlements_is_admin_email_from_context():
    """Test is_admin works when account_email is provided in query params (no account in DB)."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # No account in DB - email comes from query params
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_email": "contact@mairie.fr",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "email_contact"


def test_api_entitlements_is_admin_no_email():
    """Test is_admin when no email is available - only population check applies."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=2000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # Account with no email
    factories.AccountFactory(
        organization=organization,
        type="user",
        email="",
        external_id="xyz",
    )

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "population"


@pytest.mark.parametrize(
    "account_key,account_key_value,account_key_http_alias",
    [["external_id", "xyz", "id"], ["email", "other@example.com", "email"]],
)
@pytest.mark.parametrize(
    "population,threshold,expected_admin",
    [
        (4000, 5000, True),  # Under custom threshold -> admin
        (5000, 5000, False),  # At custom threshold -> not admin
        (2000, 1000, False),  # Over custom threshold -> not admin
    ],
)
def test_api_entitlements_is_admin_custom_auto_admin_population_threshold(
    account_key,
    account_key_value,
    account_key_http_alias,
    population,
    threshold,
    expected_admin,
):
    """Test that auto_admin_population_threshold can be configured per service."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        population=population,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={
            "entitlements_api_key": "test_token",
            "auto_admin_population_threshold": threshold,
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    account_kwargs = {
        "organization": organization,
        "type": "user",
        account_key: account_key_value,
    }
    if account_key != "email":
        account_kwargs["email"] = "someone@example.com"
    factories.AccountFactory(**account_kwargs)

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
    assert data["entitlements"]["is_admin"] is expected_admin


def test_api_entitlements_is_admin_role_takes_priority():
    """Test that an explicit admin role takes priority over ADC-specific checks."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

    # Account with admin role
    factories.AccountFactory(
        organization=organization,
        type="user",
        email="contact@mairie.fr",
        external_id="xyz",
        roles=["admin"],
    )

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
    # Admin role should take priority, resolved at organization level
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "organization"


# --- auto_admin metadata tests ---


def test_api_entitlements_auto_admin_all():
    """Test auto_admin=all grants admin regardless of population."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        population=10000,  # Well over default threshold
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"auto_admin": "all"},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        email="someone@example.com",
        external_id="xyz",
    )

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "auto_admin"


def test_api_entitlements_auto_admin_manual_blocks_population():
    """Test auto_admin=manual prevents population-based admin even under threshold."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        population=100,  # Well under default threshold
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"auto_admin": "manual"},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        email="someone@example.com",
        external_id="xyz",
    )

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
    assert data["entitlements"]["is_admin"] is False


def test_api_entitlements_auto_admin_manual_email_contact_still_works():
    """Test auto_admin=manual does not prevent email contact match."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        adresse_messagerie="contact@mairie.fr",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"auto_admin": "manual"},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        email="contact@mairie.fr",
        external_id="xyz",
    )

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "email_contact"


def test_api_entitlements_auto_admin_manual_explicit_role_still_works():
    """Test auto_admin=manual does not prevent explicit admin role."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        population=5000,
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"auto_admin": "manual"},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        email="someone@example.com",
        external_id="xyz",
        roles=["admin"],
    )

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "organization"


def test_api_entitlements_auto_admin_not_set_falls_back_to_population():
    """Test that when auto_admin is not in metadata, population check is used (existing behavior)."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        population=2000,  # Under default threshold
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    # No auto_admin in metadata
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"some_other_key": "value"},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        email="someone@example.com",
        external_id="xyz",
    )

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
    assert data["entitlements"]["is_admin"] is True
    assert data["entitlements"]["is_admin_resolve_level"] == "population"


def test_api_subscription_patch_auto_admin_valid():
    """Test PATCH with valid auto_admin value persists correctly."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"existing_key": "keep_me"},
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {"metadata": {"auto_admin": "all"}},
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["auto_admin"] == "all"
    # Existing metadata keys should be preserved
    assert data["metadata"]["existing_key"] == "keep_me"

    # Verify it can be changed to manual
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {"metadata": {"auto_admin": "manual"}},
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["auto_admin"] == "manual"
    assert data["metadata"]["existing_key"] == "keep_me"


def test_api_subscription_patch_auto_admin_invalid():
    """Test PATCH with invalid auto_admin value is rejected."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
    )

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {"metadata": {"auto_admin": "invalid_value"}},
        format="json",
    )
    assert response.status_code == 400


def test_api_subscription_create_auto_admin_invalid():
    """Test that creating a subscription with an invalid auto_admin value is rejected."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # No existing subscription — this is a create (upsert)
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {"metadata": {"auto_admin": "invalid_value"}},
        format="json",
    )
    assert response.status_code == 400


def test_api_subscription_create_auto_admin_valid():
    """Test that creating a subscription with a valid auto_admin value succeeds."""

    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # No existing subscription — this is a create (upsert)
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/"
        f"services/{service.id}/subscription/",
        {"metadata": {"auto_admin": "all"}},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["auto_admin"] == "all"


def test_api_adc_entitlements_unknown_siret():
    """Test ADC entitlements endpoint with a SIRET that matches no organization."""

    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )

    client = APIClient()
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": "00000000000000",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["operator"] is None
    assert data["entitlements"]["can_access"] is False
    assert data["entitlements"]["can_access_reason"] == "no_organization"
