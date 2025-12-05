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
            "url": operator.url,
            "is_active": operator.is_active,
            "user_role": "admin",
            "scope": operator.scope,
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
        "url": operator.url,
        "is_active": operator.is_active,
        "user_role": "admin",
        "scope": operator.scope,
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
