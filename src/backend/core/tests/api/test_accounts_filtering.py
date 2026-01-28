"""
Test account filtering, search, and ordering API endpoints.
"""

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


@pytest.fixture(name="filtering_setup")
def fixture_filtering_setup():
    """Setup accounts with various types and roles for filtering tests."""
    user = factories.UserFactory()
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    account1 = factories.AccountFactory(
        organization=organization,
        email="alice@example.com",
        external_id="ext-alice",
        type="user",
        roles=["admin", "editor"],
    )
    account2 = factories.AccountFactory(
        organization=organization,
        email="bob@example.com",
        external_id="ext-bob",
        type="user",
        roles=["viewer"],
    )
    account3 = factories.AccountFactory(
        organization=organization,
        email="inbox@example.com",
        external_id="ext-inbox",
        type="mailbox",
        roles=["admin"],
    )

    return {
        "user": user,
        "operator": operator,
        "organization": organization,
        "account1": account1,
        "account2": account2,
        "account3": account3,
    }


def _accounts_url(operator, organization):
    return (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/accounts/"
    )


def test_api_accounts_filter_by_type(filtering_setup):
    """Filter accounts by type should return only matching accounts."""
    client = APIClient()
    client.force_login(filtering_setup["user"])
    url = _accounts_url(filtering_setup["operator"], filtering_setup["organization"])

    response = client.get(url, {"type": "user"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert all(r["type"] == "user" for r in results)

    response = client.get(url, {"type": "mailbox"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["type"] == "mailbox"


def test_api_accounts_filter_by_role(filtering_setup):
    """Filter accounts by role should return accounts containing that role."""
    client = APIClient()
    client.force_login(filtering_setup["user"])
    url = _accounts_url(filtering_setup["operator"], filtering_setup["organization"])

    response = client.get(url, {"role": "admin"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    emails = {r["email"] for r in results}
    assert emails == {"alice@example.com", "inbox@example.com"}

    response = client.get(url, {"role": "viewer"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["email"] == "bob@example.com"


def test_api_accounts_search_by_email(filtering_setup):
    """Search should match accounts by email."""
    client = APIClient()
    client.force_login(filtering_setup["user"])
    url = _accounts_url(filtering_setup["operator"], filtering_setup["organization"])

    response = client.get(url, {"search": "alice"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["email"] == "alice@example.com"


def test_api_accounts_search_by_external_id(filtering_setup):
    """Search should match accounts by external_id."""
    client = APIClient()
    client.force_login(filtering_setup["user"])
    url = _accounts_url(filtering_setup["operator"], filtering_setup["organization"])

    response = client.get(url, {"search": "ext-bob"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["external_id"] == "ext-bob"


def test_api_accounts_ordering(filtering_setup):
    """Ordering should sort accounts correctly."""
    client = APIClient()
    client.force_login(filtering_setup["user"])
    url = _accounts_url(filtering_setup["operator"], filtering_setup["organization"])

    response = client.get(url, {"ordering": "email"})
    assert response.status_code == 200
    results = response.json()["results"]
    emails = [r["email"] for r in results]
    assert emails == sorted(emails)

    response = client.get(url, {"ordering": "-email"})
    assert response.status_code == 200
    results = response.json()["results"]
    emails = [r["email"] for r in results]
    assert emails == sorted(emails, reverse=True)


def test_api_accounts_combined_filters(filtering_setup):
    """Combined type + role + search filters should all apply."""
    client = APIClient()
    client.force_login(filtering_setup["user"])
    url = _accounts_url(filtering_setup["operator"], filtering_setup["organization"])

    # type=user AND role=admin => only alice
    response = client.get(url, {"type": "user", "role": "admin"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["email"] == "alice@example.com"

    # type=user AND role=admin AND search=bob => no results
    response = client.get(url, {"type": "user", "role": "admin", "search": "bob"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 0
