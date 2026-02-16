"""
Test organizations accounts API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db


@pytest.fixture(name="account_test_setup")
def fixture_account_test_setup():
    """Fixture for setting up users, operators, and organizations for account tests."""
    user = factories.UserFactory()
    user2 = factories.UserFactory()

    operator = factories.OperatorFactory(
        config={"external_management_api_key": "test-external-api-key-12345"}
    )
    operator2 = factories.OperatorFactory(
        config={"external_management_api_key": "test-external-api-key-abcd"}
    )
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory(name="C")
    organization_nok2 = factories.OrganizationFactory(name="D")
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

    service1 = factories.ServiceFactory(name="test-service-1")
    service2 = factories.ServiceFactory(name="test-service-2")

    return {
        "user": user,
        "user2": user2,
        "operator": operator,
        "operator2": operator2,
        "operator3": operator3,
        "organization_ok1": organization_ok1,
        "organization_ok2": organization_ok2,
        "organization_nok1": organization_nok1,
        "organization_nok2": organization_nok2,
        "service1": service1,
        "service2": service2,
    }


##
## Create accounts
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_create(account_test_setup, auth_method):
    """Authenticated auth method (user or operator) should be able to create accounts."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization_ok1 = account_test_setup["organization_ok1"]

    assert models.Account.objects.count() == 0

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/accounts/",
        data={
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 201
    assert_equals_partial(
        response.json(),
        {
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
        },
    )

    assert models.Account.objects.count() == 1
    assert (
        models.Account.objects.get(email="test@example.com").organization
        == organization_ok1
    )


def test_api_organizations_accounts_create_anonymous(account_test_setup):
    """Anonymous users should not be allowed to create accounts."""
    client = APIClient()

    operator = account_test_setup["operator"]
    organization_ok1 = account_test_setup["organization_ok1"]

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/accounts/",
        data={
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }


def test_api_organizations_accounts_create_not_allowed_wrong_key(account_test_setup):
    """Operators using external API key should not be able to create accounts for other operators."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-67890")

    operator = account_test_setup["operator"]
    organization_ok1 = account_test_setup["organization_ok1"]

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/accounts/",
        data={
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Token verification failed"}


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_create_not_allowed_authent(
    account_test_setup, auth_method
):
    """Authenticated auth method (user or operator) should not be able to create accounts for other organizations."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization = account_test_setup["organization_nok1"]

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/",
        data={
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


##
## Upsert accounts (POST with existing email+type updates roles)
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_upsert_updates_roles(
    account_test_setup, auth_method
):
    """A second POST with the same email+type should update roles instead of failing."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization = account_test_setup["organization_ok1"]
    url = f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"

    # First POST: create the account
    response = client.post(
        url,
        data={
            "email": "alice@collectivite.fr",
            "type": "user",
            "roles": [],
        },
        format="json",
    )
    assert response.status_code == 201
    account_id = response.json()["id"]
    assert response.json()["roles"] == []
    assert models.Account.objects.count() == 1

    # Second POST: same email+type, different roles => upsert
    response = client.post(
        url,
        data={
            "email": "alice@collectivite.fr",
            "type": "user",
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["id"] == account_id
    assert response.json()["roles"] == ["admin"]
    # Still only one account
    assert models.Account.objects.count() == 1


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_upsert_different_type_creates(
    account_test_setup, auth_method
):
    """POST with the same email but different type should create a new account."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization = account_test_setup["organization_ok1"]
    url = f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"

    # Create a user account
    response = client.post(
        url,
        data={"email": "shared@collectivite.fr", "type": "user"},
        format="json",
    )
    assert response.status_code == 201

    # Create a mailbox account with the same email
    response = client.post(
        url,
        data={"email": "shared@collectivite.fr", "type": "mailbox"},
        format="json",
    )
    assert response.status_code == 201
    assert models.Account.objects.count() == 2


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_upsert_updates_external_id(
    account_test_setup, auth_method
):
    """Upsert should also update external_id if provided."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization = account_test_setup["organization_ok1"]
    url = f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"

    # Create without external_id
    response = client.post(
        url,
        data={"email": "bob@collectivite.fr", "type": "user"},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["external_id"] == ""

    # Upsert with external_id
    response = client.post(
        url,
        data={
            "email": "bob@collectivite.fr",
            "type": "user",
            "external_id": "oidc-sub-456",
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["external_id"] == "oidc-sub-456"
    assert response.json()["roles"] == ["admin"]
    assert models.Account.objects.count() == 1


##
## List accounts
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_list(account_test_setup, auth_method):
    """Authenticated auth method (user or operator) should be able to list accounts of an organization."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization_ok1 = account_test_setup["organization_ok1"]
    organization_ok2 = account_test_setup["organization_ok2"]

    factories.AccountFactory(email="test@org1.com", organization=organization_ok1)
    factories.AccountFactory(email="test2@org1.com", organization=organization_ok1)
    factories.AccountFactory(email="test3@org1.com", organization=organization_ok1)
    factories.AccountFactory(email="test4@org2.com", organization=organization_ok2)
    factories.AccountFactory(email="test5@org2.com", organization=organization_ok2)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/accounts/"
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "count": 3,
            "results": [
                {
                    "email": "test@org1.com",
                },
                {
                    "email": "test2@org1.com",
                },
                {
                    "email": "test3@org1.com",
                },
            ],
        },
    )


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_list_not_allowed_operator(
    account_test_setup, auth_method
):
    """Authenticated auth method (user or operator) should not be able to list accounts of other organizations."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization = account_test_setup["organization_nok1"]

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


def test_api_organizations_accounts_list_anonymous(account_test_setup):
    """
    Authenticated auth method (user or operator) should not be able to
    list accounts of an organization if anonymous.
    """
    client = APIClient()

    operator = account_test_setup["operator"]
    organization = account_test_setup["organization_nok1"]

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"
    )
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }


##
## Get account
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_get(account_test_setup, auth_method):
    """Operators using external API key should not be able to get accounts of other operators."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(
        email="test@example.com",
        organization=organization,
        external_id="1234567890",
        type="user",
        roles=["admin"],
    )

    response = client.get(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
            "service_links": [],
        },
    )


def test_api_organizations_accounts_get_operator_do_not_exists(account_test_setup):
    """Operators using external API key that do not exist should not be able to get accounts."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-wrong")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(
        email="test@example.com", organization=organization
    )

    response = client.get(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 401
    assert response.json() == {"detail": "Token verification failed"}


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_get_operator_not_allowed(
    account_test_setup, auth_method
):
    """Operators using external API key should not be able to get accounts of other operators."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user2"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-abcd")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(
        email="test@example.com", organization=organization
    )

    response = client.get(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


##
## Patch account
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_patch_account(account_test_setup, auth_method):
    """Authenticated auth method (user or operator) should be able to patch an account."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(
        email="test@example.com",
        organization=organization,
        external_id="1234567890",
        type="user",
        roles=[],
    )

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/",
        data={
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "roles": ["admin"],
        },
    )

    account.refresh_from_db()
    assert account.roles == ["admin"]


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_patch_account_operator_not_allowed(
    account_test_setup, auth_method
):
    """Authenticated auth method (user or operator) should not be able to patch an account of other operators."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user2"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-abcd")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(organization=organization)

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/",
        data={
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


def test_api_organizations_accounts_patch_account_operator_do_not_exists(
    account_test_setup,
):
    """Authenticated auth method (user or operator) should not be able to patch an account of other operators."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-wrong")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(organization=organization)

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/",
        data={
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Token verification failed"}


##
## Patch service links
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_patch_service_link(account_test_setup, auth_method):
    """Authenticated auth method (user or operator) should be able to patch service links of an account."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    operator = account_test_setup["operator"]
    organization_ok1 = account_test_setup["organization_ok1"]
    service1 = account_test_setup["service1"]

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/accounts/",
        data={
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
            "service_links": [],
        },
        format="json",
    )
    account = response.json()
    # Assert that the account is created. With no service links.
    assert_equals_partial(
        account,
        {
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
        },
    )

    # Patch the service link for the account.
    response = client.patch(
        f"/api/v1.0/accounts/{account['id']}/services/{service1.id}/",
        data={
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 200
    assert_equals_partial(
        response.json(),
        {
            "roles": ["admin"],
        },
    )

    # Assert that the service link is created and updated
    response = client.get(f"/api/v1.0/accounts/{account['id']}/")
    account_data = response.json()
    assert_equals_partial(
        account_data,
        {
            "email": "test@example.com",
            "external_id": "1234567890",
            "type": "user",
            "roles": ["admin"],
            "service_links": [
                {
                    "roles": ["admin"],
                    "service": {"id": service1.id, "name": "test-service-1"},
                }
            ],
        },
    )


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_patch_service_link_operator_not_allowed(
    account_test_setup, auth_method
):
    """Authenticated auth method (user or operator) should be able to patch service links of an account."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user2"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-abcd")

    organization_ok1 = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(
        email="test@example.com", organization=organization_ok1
    )
    service1 = account_test_setup["service1"]

    # Patch the service link for the account.
    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/services/{service1.id}/",
        data={
            "roles": ["admin"],
        },
        format="json",
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


##
## Delete account
##


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_delete(account_test_setup, auth_method):
    """Authenticated auth method (user or operator) should be able to delete an account."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-12345")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(
        email="test@example.com",
        organization=organization,
        external_id="1234567890",
        type="user",
        roles=["admin"],
    )

    assert models.Account.objects.filter(id=account.id).exists()

    response = client.delete(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 204

    assert not models.Account.objects.filter(id=account.id).exists()


@pytest.mark.parametrize("auth_method", ["user", "external_api_key"])
def test_api_organizations_accounts_delete_operator_not_allowed(
    account_test_setup, auth_method
):
    """Authenticated auth method (user or operator) should not be able to delete accounts of other operators."""
    client = APIClient()
    if auth_method == "user":
        client.force_login(account_test_setup["user2"])
    elif auth_method == "external_api_key":
        client.credentials(HTTP_AUTHORIZATION="Bearer test-external-api-key-abcd")

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(organization=organization)

    response = client.delete(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


def test_api_organizations_accounts_delete_anonymous(account_test_setup):
    """Anonymous users should not be able to delete accounts."""
    client = APIClient()

    organization = account_test_setup["organization_ok1"]
    account = factories.AccountFactory(organization=organization)

    response = client.delete(f"/api/v1.0/accounts/{account.id}/")
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }
