"""
Test users API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


def test_api_operators_list_anonymous():
    """Anonymous users should not be allowed to list operators."""
    factories.UserFactory.create_batch(2)
    client = APIClient()
    response = client.get("/api/v1.0/operators/")
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }


def test_api_operators_list_authenticated():
    """Authenticated users should be able to list operators for which they have a UserOperatorRole."""
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
    response = client.get("/api/v1.0/operators/")
    content = response.json()
    results = content["results"]
    assert len(results) == 1
    assert results == [
        {
            "id": str(operator.id),
            "name": operator.name,
            "siret": operator.siret,
            "url": operator.url,
            "is_active": operator.is_active,
            "user_role": "admin",
            "config": operator.config,
        }
    ]


def test_api_operators_retrieve_authenticated():
    """Authenticated users should be able to retrieve operators for which they have a UserOperatorRole."""
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
    response = client.get(f"/api/v1.0/operators/{operator.id}/")
    content = response.json()
    results = content
    assert results == {
        "id": str(operator.id),
        "name": operator.name,
        "siret": operator.siret,
        "url": operator.url,
        "is_active": operator.is_active,
        "user_role": "admin",
        "config": operator.config,
    }


def test_api_operators_retrieve_authenticated_no_role():
    """Authenticated users should not be able to retrieve operators for which they have no UserOperatorRole."""
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
    response = client.get(f"/api/v1.0/operators/{operator2.id}/")
    assert response.status_code == 404
    assert response.json() == {"detail": "No Operator matches the given query."}


def test_api_operators_services_no_role():
    """Users should not be able to list services for an operator they have no role on."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    other_operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    service = factories.ServiceFactory(is_active=True)
    factories.OperatorServiceConfigFactory(operator=other_operator, service=service)

    response = client.get(f"/api/v1.0/operators/{other_operator.id}/services/")
    assert response.status_code == 404


def test_api_operators_services_with_role():
    """Users should be able to list services for an operator they have a role on."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    service = factories.ServiceFactory(is_active=True)
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.get(f"/api/v1.0/operators/{operator.id}/services/")
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == service.id


def test_api_operators_list_superuser():
    """Superusers should be able to list all operators regardless of roles."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)

    operator1 = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()

    response = client.get("/api/v1.0/operators/")
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    returned_ids = {r["id"] for r in results}
    assert returned_ids == {str(operator1.id), str(operator2.id), str(operator3.id)}


def test_api_operators_retrieve_superuser():
    """Superusers should be able to retrieve any operator regardless of roles."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()

    response = client.get(f"/api/v1.0/operators/{operator.id}/")
    assert response.status_code == 200
    assert response.json()["id"] == str(operator.id)


def test_api_operators_exposed_config():
    """Test that the exposed config is the expected one."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory(
        config={"idps": ["idp1", "idp2"], "secret_key": "secret_key"}
    )
    operator.save()

    factories.UserOperatorRoleFactory(user=user, operator=operator)

    # Retrieve route.
    response = client.get(f"/api/v1.0/operators/{operator.id}/")
    assert response.status_code == 200
    keys = list(response.json()["config"].keys())
    assert keys == ["idps"]

    # List route.
    response = client.get("/api/v1.0/operators/")
    results = response.json()["results"]
    assert len(results) == 1
    keys = list(results[0]["config"].keys())
    assert keys == ["idps"]


def test_api_operators_list_superuser_page_size():
    """Superusers should be able to list all operators using page_size parameter."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)

    factories.OperatorFactory.create_batch(25)

    # Default page size should be 20
    response = client.get("/api/v1.0/operators/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 25
    assert len(data["results"]) == 20

    # With page_size=100, all operators should be returned
    response = client.get("/api/v1.0/operators/?page_size=100")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 25
    assert len(data["results"]) == 25


def _operator_with_organization():
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    return operator, organization


def _operator_pages(operator, organization):
    base = f"/api/v1.0/operators/{operator.id}"
    return [
        f"{base}/organizations/",
        f"{base}/organizations/{organization.id}/",
        f"{base}/organizations/{organization.id}/services/",
        f"{base}/organizations/{organization.id}/accounts/",
        f"{base}/metrics/keys/",
    ]


def test_api_operators_superuser_opens_any_operator():
    """A superuser lists every operator, so can open one without a role in it."""
    client = APIClient()
    client.force_login(factories.UserFactory(is_superuser=True))
    operator, organization = _operator_with_organization()

    for url in _operator_pages(operator, organization):
        assert client.get(url).status_code == 200, url


def test_api_operators_superuser_organization_of_another_operator():
    """The organization in the URL must still be managed by the operator."""
    client = APIClient()
    client.force_login(factories.UserFactory(is_superuser=True))
    operator, _ = _operator_with_organization()
    _, other_organization = _operator_with_organization()

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{other_organization.id}"
        "/services/"
    )
    assert response.status_code == 403


def test_api_operators_user_without_role_cannot_open_operator():
    """A regular user without a role in the operator is refused."""
    client = APIClient()
    client.force_login(factories.UserFactory())
    operator, organization = _operator_with_organization()

    for url in _operator_pages(operator, organization):
        assert client.get(url).status_code in (403, 404), url
