"""
Test the query filters of the organizations list API.
"""

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "rpnt_filter,expected",
    [
        ("a", {"Conforme"}),
        ("1.a", {"Conforme", "Site"}),
        ("2.a", {"Conforme", "Messagerie"}),
        ("!a", {"Site", "Messagerie", "Rien", "Vide", "Nul"}),
        ("!1.a", {"Messagerie", "Rien", "Vide", "Nul"}),
        ("!2.a", {"Site", "Rien", "Vide", "Nul"}),
    ],
)
def test_api_organizations_list_filter_rpnt(rpnt_filter, expected):
    """The organizations list can be filtered on an RPNT meta-criterion, or its negative."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    for name, rpnt in [
        ("Conforme", ["1.1", "1.a", "2.1", "2.a", "a"]),
        ("Site", ["1.1", "1.a"]),
        ("Messagerie", ["2.1", "2.a"]),
        ("Rien", ["1.1", "2.1"]),
        ("Vide", []),
        ("Nul", None),
    ]:
        factories.OperatorOrganizationRoleFactory(
            operator=operator,
            organization=factories.OrganizationFactory(name=name, rpnt=rpnt),
        )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/?rpnt={rpnt_filter}"
    )
    assert response.status_code == 200
    assert {r["name"] for r in response.json()["results"]} == expected


@pytest.mark.parametrize("rpnt_filter", ["1.1", "!1.1", "b", "!", "!!a", "a "])
def test_api_organizations_list_filter_rpnt_unsupported(rpnt_filter):
    """Only the three meta-criteria are filterable; anything else is a 400, not a silent no-op."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=factories.OrganizationFactory()
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/", {"rpnt": rpnt_filter}
    )
    assert response.status_code == 400
    assert "rpnt" in response.json()
