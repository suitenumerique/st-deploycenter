"""Tests for the operator metrics dashboard API."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


def _url(operator):
    return f"/api/v1.0/operators/{operator.id}/metrics/"


def _keys_url(operator):
    return f"/api/v1.0/operators/{operator.id}/metrics/keys/"


@pytest.fixture(name="setup")
def fixture_setup():
    """An operator with two organizations, one service and storage metrics.

    Organization "alpha" holds two account metrics (one user, one mailbox),
    organization "beta" holds one. A second operator holds its own organization
    and metric, which must never show up in the first operator's results.
    """
    user = factories.UserFactory()
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    service = factories.ServiceFactory(type="drive")
    other_service = factories.ServiceFactory(type="messages")

    alpha = factories.OrganizationFactory(name="Alpha")
    beta = factories.OrganizationFactory(name="Beta")
    for organization in (alpha, beta):
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization
        )

    alpha_user = factories.AccountFactory(
        organization=alpha, type="user", email="user@alpha.test"
    )
    alpha_mailbox = factories.AccountFactory(
        organization=alpha, type="mailbox", email=""
    )
    beta_user = factories.AccountFactory(
        organization=beta, type="user", email="user@beta.test"
    )

    factories.MetricFactory(
        key="storage_used",
        value=Decimal("100"),
        service=service,
        organization=alpha,
        account=alpha_user,
    )
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("20"),
        service=service,
        organization=alpha,
        account=alpha_mailbox,
    )
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("7"),
        service=service,
        organization=beta,
        account=beta_user,
    )
    # Same organization, different key and different service: both must be
    # filtered out by the key/service params.
    factories.MetricFactory(
        key="user_count",
        value=Decimal("3"),
        service=service,
        organization=alpha,
        account=None,
    )
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("999"),
        service=other_service,
        organization=alpha,
        account=alpha_user,
    )

    # A second operator with its own organization and metric.
    other_operator = factories.OperatorFactory()
    foreign = factories.OrganizationFactory(name="Foreign")
    factories.OperatorOrganizationRoleFactory(
        operator=other_operator, organization=foreign
    )
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("5000"),
        service=service,
        organization=foreign,
        account=None,
    )

    return {
        "user": user,
        "operator": operator,
        "other_operator": other_operator,
        "service": service,
        "other_service": other_service,
        "alpha": alpha,
        "beta": beta,
        "foreign": foreign,
        "alpha_user": alpha_user,
        "alpha_mailbox": alpha_mailbox,
        "beta_user": beta_user,
    }


@pytest.fixture(name="client")
def fixture_client(setup):
    """An API client logged in as the operator's user."""
    client = APIClient()
    client.force_login(setup["user"])
    return client


# -- Authentication and scoping


def test_api_operator_metrics_anonymous(setup):
    """Anonymous users cannot read metrics."""
    response = APIClient().get(
        _url(setup["operator"]), {"key": "storage_used", "service": setup["service"].id}
    )
    assert response.status_code == 401


def test_api_operator_metrics_other_operator(setup):
    """A user without a role on the operator is denied."""
    client = APIClient()
    client.force_login(setup["user"])

    response = client.get(
        _url(setup["other_operator"]),
        {"key": "storage_used", "service": setup["service"].id},
    )
    assert response.status_code == 403


def test_api_operator_metrics_excludes_other_operators_organizations(setup, client):
    """Metrics of an organization the operator has no role in are never returned."""
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("10"),
        service=setup["service"],
        organization=setup["alpha"],
        account=None,
    )

    response = client.get(
        _url(setup["operator"]),
        {"key": "storage_used", "service": setup["service"].id, "account_type": "none"},
    )
    assert response.status_code == 200
    data = response.json()

    # The foreign organization's row has no account either.
    assert data["count"] == 1
    assert data["results"][0]["organization"]["name"] == "Alpha"


def test_api_operator_metrics_aggregation_excludes_other_operators(setup, client):
    """The aggregate covers the operator's organizations only."""
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("10"),
        service=setup["service"],
        organization=setup["alpha"],
        account=None,
    )

    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "none",
            "agg": "sum",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Without the foreign organization's 5000.
    assert Decimal(data["value"]) == Decimal("10")
    assert data["count"] == 1


# -- Query parameter validation


def test_api_operator_metrics_requires_key(setup, client):
    """The key param is required."""
    response = client.get(
        _url(setup["operator"]),
        {"service": setup["service"].id, "account_type": "user"},
    )
    assert response.status_code == 400
    assert "key" in response.json()


def test_api_operator_metrics_requires_service(setup, client):
    """The service param is required."""
    response = client.get(
        _url(setup["operator"]), {"key": "storage_used", "account_type": "user"}
    )
    assert response.status_code == 400
    assert "service" in response.json()


def test_api_operator_metrics_requires_account_type(setup, client):
    """The account_type param is required: account types are never summed together."""
    response = client.get(
        _url(setup["operator"]), {"key": "storage_used", "service": setup["service"].id}
    )
    assert response.status_code == 400
    assert "account_type" in response.json()


def test_api_operator_metrics_service_not_an_integer(setup, client):
    """A malformed service id is a 400, not a 500 from the ORM."""
    response = client.get(
        _url(setup["operator"]),
        {"key": "storage_used", "service": "abc", "account_type": "user"},
    )
    assert response.status_code == 400
    assert "service" in response.json()


def test_api_operator_metrics_unknown_service(setup, client):
    """An integer service id that matches nothing is a 404."""
    response = client.get(
        _url(setup["operator"]),
        {"key": "storage_used", "service": 999999, "account_type": "user"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["error"]


def test_api_operator_metrics_invalid_aggregation(setup, client):
    """Only sum and avg are accepted."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "agg": "max",
        },
    )
    assert response.status_code == 400
    assert "agg" in response.json()


def test_api_operator_metrics_invalid_group_by(setup, client):
    """An unsupported group_by is rejected instead of silently ignored."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "group_by": "account",
        },
    )
    assert response.status_code == 400
    assert "group_by" in response.json()


def test_api_operator_metrics_malformed_organization_id(setup, client):
    """A malformed organization id names the offending value."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "organizations": "not-a-uuid",
        },
    )
    assert response.status_code == 400
    assert response.json()["organizations"] == ["'not-a-uuid' is not a valid UUID."]


def test_api_operator_metrics_malformed_account_id(setup, client):
    """A malformed account id names the offending value."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "accounts": "not-a-uuid",
        },
    )
    assert response.status_code == 400
    assert response.json()["accounts"] == ["'not-a-uuid' is not a valid UUID."]


# -- Filtering


def test_api_operator_metrics_filters_by_key_and_service(setup, client):
    """Only the requested key and service are returned; "none" selects the rows
    stored without an account."""
    response = client.get(
        _url(setup["operator"]),
        {"key": "user_count", "service": setup["service"].id, "account_type": "none"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    assert data["results"][0]["key"] == "user_count"
    assert data["results"][0]["account"] is None


def test_api_operator_metrics_account_types_are_not_mixed(setup, client):
    """An organization-level row and its users' rows are never added up."""
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("500"),
        service=setup["service"],
        organization=setup["alpha"],
        account=factories.AccountFactory(
            organization=setup["alpha"], type="organization"
        ),
    )

    def grouped(account_type):
        response = client.get(
            _url(setup["operator"]),
            {
                "key": "storage_used",
                "service": setup["service"].id,
                "account_type": account_type,
                "group_by": "organization",
            },
        )
        assert response.status_code == 200
        return [
            (result["organization"]["name"], Decimal(result["value"]))
            for result in response.json()["results"]
        ]

    assert grouped("user") == [("Alpha", Decimal("100")), ("Beta", Decimal("7"))]
    assert grouped("organization") == [("Alpha", Decimal("500"))]


def test_api_operator_metrics_filters_by_organization(setup, client):
    """The organizations param narrows the results."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "organizations": str(setup["beta"].id),
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    assert data["results"][0]["organization"]["name"] == "Beta"


def test_api_operator_metrics_organization_filter_drops_foreign_ids(setup, client):
    """A foreign organization id cannot widen the scope."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "organizations": f"{setup['beta'].id},{setup['foreign'].id}",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    assert data["results"][0]["organization"]["name"] == "Beta"


def test_api_operator_metrics_only_foreign_organizations(setup, client):
    """Asking exclusively for organizations out of scope is reported."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "organizations": str(setup["foreign"].id),
        },
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": "No valid organizations found for the given IDs."
    }


def test_api_operator_metrics_filters_by_account_type(setup, client):
    """The account_type param narrows the results."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "mailbox",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    assert data["results"][0]["account"]["type"] == "mailbox"


def test_api_operator_metrics_filters_by_accounts(setup, client):
    """The accounts param narrows the results."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "accounts": str(setup["beta_user"].id),
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    assert data["results"][0]["account"]["email"] == "user@beta.test"


# -- Aggregation and grouping


def test_api_operator_metrics_sum(setup, client):
    """agg=sum returns the total and the number of metrics behind it."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "agg": "sum",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["aggregation"] == "sum"
    assert data["service_id"] == setup["service"].id
    assert Decimal(data["value"]) == Decimal("107")
    assert data["count"] == 2


def test_api_operator_metrics_avg(setup, client):
    """agg=avg returns the mean over the same rows."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "agg": "avg",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["aggregation"] == "avg"
    assert Decimal(data["value"]) == Decimal("53.5")
    assert data["count"] == 2


def test_api_operator_metrics_sum_beyond_fourteen_digits(setup, client):
    """A total past 14 integer digits (100 TB in bytes) is returned, not a 500."""
    for account in (setup["alpha_user"], setup["beta_user"]):
        factories.MetricFactory(
            key="storage_bytes",
            value=Decimal("90000000000000"),
            service=setup["service"],
            organization=account.organization,
            account=account,
        )

    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_bytes",
            "service": setup["service"].id,
            "account_type": "user",
            "agg": "sum",
        },
    )
    assert response.status_code == 200
    assert Decimal(response.json()["value"]) == Decimal("180000000000000")


def test_api_operator_metrics_aggregation_without_rows(setup, client):
    """Aggregating nothing is zero, not null."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "does_not_exist",
            "service": setup["service"].id,
            "account_type": "user",
            "agg": "sum",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert Decimal(data["value"]) == Decimal("0")
    assert data["count"] == 0


def test_api_operator_metrics_group_by_organization(setup, client):
    """group_by=organization sums each organization and names the grouping."""
    factories.MetricFactory(
        key="storage_used",
        value=Decimal("30"),
        service=setup["service"],
        organization=setup["alpha"],
        account=factories.AccountFactory(organization=setup["alpha"], type="user"),
    )

    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "group_by": "organization",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["grouped_by"] == "organization"
    assert data["count"] == 2
    assert [
        (result["organization"]["name"], Decimal(result["value"]))
        for result in data["results"]
    ] == [("Alpha", Decimal("130")), ("Beta", Decimal("7"))]


def test_api_operator_metrics_group_by_organization_with_account_type(setup, client):
    """Grouping applies after the account_type filter."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "group_by": "organization",
            "account_type": "mailbox",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert [
        (result["organization"]["name"], Decimal(result["value"]))
        for result in data["results"]
    ] == [("Alpha", Decimal("20"))]


# -- Pagination


def test_api_operator_metrics_list_is_paginated(setup, client):
    """The listing is bounded: a page, a total and a link to the next one."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "page_size": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 2
    assert len(data["results"]) == 1
    assert data["next"] is not None
    assert data["previous"] is None


def test_api_operator_metrics_pagination_covers_every_row_once(setup, client):
    """Walking the pages yields each metric exactly once."""
    seen = []
    for page in (1, 2):
        response = client.get(
            _url(setup["operator"]),
            {
                "key": "storage_used",
                "service": setup["service"].id,
                "account_type": "user",
                "page_size": 1,
                "page": page,
            },
        )
        assert response.status_code == 200
        seen.extend(result["id"] for result in response.json()["results"])

    assert len(seen) == 2
    assert len(set(seen)) == 2


def test_api_operator_metrics_grouped_results_are_paginated(setup, client):
    """The grouped view is bounded too, and keeps its grouped_by marker."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "group_by": "organization",
            "page_size": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 2
    assert data["grouped_by"] == "organization"
    assert len(data["results"]) == 1
    assert data["results"][0]["organization"]["name"] == "Alpha"
    assert data["next"] is not None


# -- Metric keys


EXPECTED_KEYS = {
    "results": [
        {"key": "storage_used", "account_types": ["mailbox", "user"]},
        {"key": "user_count", "account_types": ["none"]},
    ]
}


def test_api_operator_metrics_keys(setup, client):
    """The keys endpoint lists the operator's keys, sorted and deduplicated, each
    with the account types it has data for ("none" for rows without an account)."""
    response = client.get(_keys_url(setup["operator"]))
    assert response.status_code == 200
    assert response.json() == EXPECTED_KEYS


def test_api_operator_metrics_keys_filtered_by_service(setup, client):
    """A service narrows the keys to the ones that service reported."""
    response = client.get(
        _keys_url(setup["operator"]), {"service": setup["other_service"].id}
    )
    assert response.status_code == 200
    assert response.json() == {
        "results": [{"key": "storage_used", "account_types": ["user"]}]
    }


def test_api_operator_metrics_keys_excludes_other_operators(setup, client):
    """Keys only reported by another operator's organizations are not listed."""
    factories.MetricFactory(
        key="foreign_only",
        value=Decimal("1"),
        service=setup["service"],
        organization=setup["foreign"],
        account=None,
    )

    response = client.get(_keys_url(setup["operator"]))
    assert response.status_code == 200
    assert "foreign_only" not in [row["key"] for row in response.json()["results"]]


def test_api_operator_metrics_keys_service_not_an_integer(setup, client):
    """A malformed service id is a 400, not a 500."""
    response = client.get(_keys_url(setup["operator"]), {"service": "abc"})
    assert response.status_code == 400
    assert "service" in response.json()


def test_api_operator_metrics_keys_other_operator(setup):
    """The keys endpoint is scoped by the same operator permission."""
    client = APIClient()
    client.force_login(setup["user"])

    response = client.get(_keys_url(setup["other_operator"]))
    assert response.status_code == 403


# -- Ordering


def test_api_operator_metrics_order_by_defaults_to_organization(setup, client):
    """Without order_by, grouped rows stay alphabetical."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "group_by": "organization",
        },
    )
    assert response.status_code == 200
    assert [r["organization"]["name"] for r in response.json()["results"]] == [
        "Alpha",
        "Beta",
    ]


@pytest.mark.parametrize(
    "order_by,expected",
    [("value", ["Beta", "Alpha"]), ("-value", ["Alpha", "Beta"])],
)
def test_api_operator_metrics_group_by_ordered_by_value(
    setup, client, order_by, expected
):
    """Grouped rows sort on the summed value, both directions.

    Alpha sums to 100 and Beta to 7, so the two orders are each other's reverse.
    """
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "group_by": "organization",
            "order_by": order_by,
        },
    )
    assert response.status_code == 200
    assert [r["organization"]["name"] for r in response.json()["results"]] == expected


@pytest.mark.parametrize("order_by", ["value", "-value"])
def test_api_operator_metrics_rows_ordered_by_value(setup, client, order_by):
    """Account rows sort on the metric value, both directions."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "order_by": order_by,
        },
    )
    assert response.status_code == 200

    values = [Decimal(result["value"]) for result in response.json()["results"]]
    assert values == sorted(values, reverse=order_by.startswith("-"))


def test_api_operator_metrics_order_by_value_is_fully_ordered(setup, client):
    """Rows sharing a value come back in id order, and paging covers each once.

    Sorting on value alone leaves ties in an order the database may change
    between two queries, which is how a row appears on two pages or on none, so
    the ordering carries "id" as a tie-break. Three metrics here share a value.

    Note this pins the contract rather than reproducing the failure: at this row
    count Postgres returns ties in a stable order anyway, so the assertions below
    still pass if the tie-break is removed. Only a plan change would surface it.
    """
    for _ in range(3):
        factories.MetricFactory(
            key="storage_used",
            value=Decimal("42"),
            service=setup["service"],
            organization=setup["alpha"],
            account=factories.AccountFactory(organization=setup["alpha"], type="user"),
        )

    seen = []
    for page in (1, 2, 3):
        response = client.get(
            _url(setup["operator"]),
            {
                "key": "storage_used",
                "service": setup["service"].id,
                "account_type": "user",
                "order_by": "value",
                "page": page,
                "page_size": 2,
            },
        )
        assert response.status_code == 200
        seen.extend(
            (Decimal(result["value"]), result["id"])
            for result in response.json()["results"]
        )

    # The fixture's two user rows and the three added here.
    assert len(seen) == 5
    assert len({metric_id for _, metric_id in seen}) == 5
    # The full (value, id) ordering, ties included.
    assert seen == sorted(seen)


def test_api_operator_metrics_grouped_same_name_is_ordered_by_id(setup, client):
    """Organizations sharing a name are broken apart by id, and none is lost.

    Organization.name has no unique constraint and the DPNT dataset has over a
    thousand shared names, so grouping on the name alone leaves ties the database
    may order differently per page, dropping one row and repeating another.

    Like the row-level ordering test, this pins the contract rather than
    reproducing the failure: at five rows Postgres returns the ties in id order
    anyway, so the assertions still pass with the tie-break removed. Reproducing
    it needs a plan change, which needs far more rows than a test should insert.
    """
    twins = [factories.OrganizationFactory(name="Sainte-Colombe") for _ in range(3)]
    for organization in twins:
        factories.OperatorOrganizationRoleFactory(
            operator=setup["operator"], organization=organization
        )
        factories.MetricFactory(
            key="storage_used",
            value=Decimal("50"),
            service=setup["service"],
            organization=organization,
            account=factories.AccountFactory(organization=organization, type="user"),
        )

    seen = []
    for page in (1, 2, 3, 4, 5):
        response = client.get(
            _url(setup["operator"]),
            {
                "key": "storage_used",
                "service": setup["service"].id,
                "account_type": "user",
                "group_by": "organization",
                "page": page,
                "page_size": 1,
            },
        )
        assert response.status_code == 200
        seen.extend(
            (result["organization"]["name"], result["organization"]["id"])
            for result in response.json()["results"]
        )

    # Alpha, Beta and the three twins, each exactly once.
    assert len(seen) == 5
    assert len({organization_id for _, organization_id in seen}) == 5
    assert {organization_id for _, organization_id in seen} >= {
        str(organization.id) for organization in twins
    }
    # Ties resolve on the id, so the whole sequence is ordered by (name, id).
    assert seen == sorted(seen)


def test_api_operator_metrics_invalid_order_by(setup, client):
    """An unknown ordering is a 400 naming the parameter, not a 500."""
    response = client.get(
        _url(setup["operator"]),
        {
            "key": "storage_used",
            "service": setup["service"].id,
            "account_type": "user",
            "order_by": "bogus",
        },
    )
    assert response.status_code == 400
    assert "order_by" in response.json()


# -- Operator API key
#
# Every test above authenticates with force_login, which sends no Authorization
# header, so none of them reaches the bearer-token authenticator these endpoints
# declare. The tests below do, and they cover both outcomes: a key that resolves
# and one that does not.


@pytest.fixture(name="api_key_client")
def fixture_api_key_client(setup):
    """A client holding the operator's external management key."""
    operator = setup["operator"]
    operator.external_management_api_key = "test-operator-metrics-key"
    operator.save()

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-operator-metrics-key")
    return client


def test_api_operator_metrics_with_api_key(setup, api_key_client):
    """An operator key reads the same rows the operator's user sees."""
    response = api_key_client.get(
        _url(setup["operator"]),
        {"key": "storage_used", "service": setup["service"].id, "account_type": "user"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["count"] == 2
    assert "Foreign" not in {
        result["organization"]["name"] for result in data["results"]
    }


def test_api_operator_metrics_keys_with_api_key(setup, api_key_client):
    """The keys endpoint accepts the same operator key."""
    response = api_key_client.get(_keys_url(setup["operator"]))
    assert response.status_code == 200
    assert response.json() == EXPECTED_KEYS


def test_api_operator_metrics_api_key_of_other_operator(setup):
    """A key belonging to another operator cannot read these metrics."""
    other = setup["other_operator"]
    other.external_management_api_key = "test-other-operator-key"
    other.save()

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-other-operator-key")

    response = client.get(
        _url(setup["operator"]), {"key": "storage_used", "service": setup["service"].id}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("url_for", [_url, _keys_url])
def test_api_operator_metrics_unknown_bearer_token(setup, url_for):
    """An unknown bearer token is a 401, not a 500.

    The viewset used to declare the abstract authentication base class, whose
    `model` is None, so merely carrying an Authorization header crashed the
    request in the authenticator before any view code ran.
    """
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-key")

    response = client.get(
        url_for(setup["operator"]),
        {"key": "storage_used", "service": setup["service"].id},
    )
    assert response.status_code == 401
