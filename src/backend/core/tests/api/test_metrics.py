"""Tests for the metrics API endpoints."""

from django.test import override_settings

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db

METRICS_API_KEY = "test-metrics-secret"
METRICS_AUTH_HEADER = f"Bearer {METRICS_API_KEY}"
ENDPOINT = "/api/v1.0/metrics/subscriptions-by-service/"


def _get(client, params, header=METRICS_AUTH_HEADER):
    """Helper to call the endpoint."""
    headers = {}
    if header is not None:
        headers["Authorization"] = header
    return client.get(
        ENDPOINT,
        query_params=params,
        headers=headers,
    )


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_type_basic():
    """Returns subscriptions for the requested service type."""
    client = APIClient()

    operator = factories.OperatorFactory()
    org = factories.OrganizationFactory(siret="12345678900001")
    service = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=org, service=service, operator=operator
    )

    response = _get(client, {"service_type": "drive"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"] == [
        {"siret": "12345678900001", "metrics": {"tu": 1}},
    ]


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_id_basic():
    """Returns subscriptions for the requested service id."""
    client = APIClient()

    operator = factories.OperatorFactory()
    org = factories.OrganizationFactory(siret="12345678900001")
    service = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=org, service=service, operator=operator
    )

    response = _get(client, {"service_id": service.id})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"] == [
        {"siret": "12345678900001", "metrics": {"tu": 1}},
    ]


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_id_filters():
    """Only subscriptions for the requested service id are returned."""
    client = APIClient()

    operator = factories.OperatorFactory()
    org = factories.OrganizationFactory(siret="12345678900001")
    service_a = factories.ServiceFactory(type="drive")
    service_b = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=org, service=service_a, operator=operator
    )
    factories.ServiceSubscriptionFactory(
        organization=org, service=service_b, operator=operator
    )

    response = _get(client, {"service_id": service_a.id})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_multiple():
    """Returns all active subscriptions for the type."""
    client = APIClient()

    operator = factories.OperatorFactory()
    service = factories.ServiceFactory(type="messages")

    org_a = factories.OrganizationFactory(siret="11111111100001")
    org_b = factories.OrganizationFactory(siret="22222222200001")
    factories.ServiceSubscriptionFactory(
        organization=org_a, service=service, operator=operator
    )
    factories.ServiceSubscriptionFactory(
        organization=org_b, service=service, operator=operator
    )

    response = _get(client, {"service_type": "messages"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    sirets = {r["siret"] for r in data["results"]}
    assert sirets == {"11111111100001", "22222222200001"}


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_excludes_inactive():
    """Inactive subscriptions are not returned."""
    client = APIClient()

    operator = factories.OperatorFactory()
    service = factories.ServiceFactory(type="drive")
    org = factories.OrganizationFactory(siret="12345678900001")
    factories.ServiceSubscriptionFactory(
        organization=org, service=service, operator=operator, is_active=False
    )

    response = _get(client, {"service_type": "drive"})
    assert response.status_code == 200
    assert response.json() == {"count": 0, "results": []}


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_deduplicates():
    """Org with two subscriptions to same-type services appears only once."""
    client = APIClient()

    operator = factories.OperatorFactory()
    org = factories.OrganizationFactory(siret="12345678900001")
    service_a = factories.ServiceFactory(type="drive")
    service_b = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=org, service=service_a, operator=operator
    )
    factories.ServiceSubscriptionFactory(
        organization=org, service=service_b, operator=operator
    )

    response = _get(client, {"service_type": "drive"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"] == [
        {"siret": "12345678900001", "metrics": {"tu": 1}},
    ]


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_filters_by_type():
    """Only subscriptions for the requested service type are returned."""
    client = APIClient()

    operator = factories.OperatorFactory()
    org = factories.OrganizationFactory(siret="12345678900001")
    drive_service = factories.ServiceFactory(type="drive")
    meet_service = factories.ServiceFactory(type="meet")
    factories.ServiceSubscriptionFactory(
        organization=org, service=drive_service, operator=operator
    )
    factories.ServiceSubscriptionFactory(
        organization=org, service=meet_service, operator=operator
    )

    response = _get(client, {"service_type": "meet"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["siret"] == "12345678900001"


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_empty():
    """No subscriptions for the type → empty results."""
    client = APIClient()

    response = _get(client, {"service_type": "nonexistent"})
    assert response.status_code == 200
    assert response.json() == {"count": 0, "results": []}


def test_metrics_subscriptions_by_service_anon():
    """No auth header → 403."""
    client = APIClient()
    response = _get(client, {"service_type": "drive"}, header=None)
    assert response.status_code == 403


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_wrong_key():
    """Wrong API key → 403."""
    client = APIClient()
    response = _get(client, {"service_type": "drive"}, header="Bearer wrong-key")
    assert response.status_code == 403


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_bad_header_format():
    """Malformed header → 403."""
    client = APIClient()
    response = _get(client, {"service_type": "drive"}, header="not-bearer-format")
    assert response.status_code == 403


@override_settings(METRICS_API_KEY=METRICS_API_KEY)
def test_metrics_subscriptions_by_service_missing_param():
    """Missing both service_type and service_id → 400."""
    client = APIClient()
    response = client.get(
        ENDPOINT,
        headers={"Authorization": METRICS_AUTH_HEADER},
    )
    assert response.status_code == 400


@override_settings(METRICS_API_KEY=None)
def test_metrics_subscriptions_by_service_no_key_configured():
    """When METRICS_API_KEY is not set, all requests are denied."""
    client = APIClient()
    response = _get(client, {"service_type": "drive"})
    assert response.status_code == 403
