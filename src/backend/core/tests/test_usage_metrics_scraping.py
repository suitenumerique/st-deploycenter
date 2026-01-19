"""
Tests for metrics scraping functionality with fake HTTP server.
"""

# pylint: disable=unused-argument

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

from django.db.models import Count

import pytest

from core import factories, models
from core.tasks.metrics import (
    fetch_metrics_from_service,
    fetch_usage_metrics_from_service,
    store_service_metrics,
)


class MockMetricsServer(BaseHTTPRequestHandler):
    """Mock HTTP server that serves paginated metrics data."""

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET requests with pagination support."""
        if self.path.startswith("/metrics/usage"):
            # Check authorization header
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
                return

            token = auth_header.split(" ")[1]
            if token not in ["test_token_valid"]:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid token"}).encode())
                return

            # Parse query parameters
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            limit = int(params.get("limit", [100])[0])
            offset = int(params.get("offset", [0])[0])
            account_type = params.get("account_type", [None])[0]
            account_id = params.get("account_id", [None])[0]

            # Create metrics for this page
            metrics = []

            if account_type and account_id:
                total_count = 1
                metrics.append(
                    {
                        "siret": "12345678900",
                        "account": {
                            "type": account_type,
                            "id": account_id,
                        },
                        "metrics": {"storage_used": 2147483648},
                    }
                )
            else:
                # Generate mock metrics data in the expected format
                total_count = 40  # Total orgs available
                start_idx = offset
                end_idx = min(offset + limit, total_count)

                for org_idx in range(start_idx, end_idx):
                    # Generate realistic metric values
                    metrics.append(
                        {
                            "siret": "12345678900",
                            "account": {
                                "type": "user",
                                "id": org_idx,
                            },
                            "metrics": {"storage_used": 214748364 * (org_idx + 1)},
                        }
                    )

            response_data = {"count": total_count, "results": metrics}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode())
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(name="mock_metrics_server")
def fixture_mock_metrics_server():
    """Fixture to create and manage a mock metrics server."""
    server = HTTPServer(("localhost", 8001), MockMetricsServer)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Wait for server to start
    time.sleep(0.1)

    yield server

    # Cleanup
    server.shutdown()
    server.server_close()


@pytest.fixture(name="test_organizations")
def fixture_test_organizations():
    """Fixture to create test organizations."""
    operator = factories.OperatorFactory()
    organizations = {}

    # Create organizations with SIRET codes
    for i in range(40):
        siret = f"123456789{i:02d}"
        org = factories.OrganizationFactory(
            siret=siret,
            name=f"Test Organization SIRET {i + 1}",
            departement_code_insee="75",  # Paris department
            region_code_insee="11",  # Île-de-France region
        )
        organizations[siret] = org

        # Link operator to organization
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=org, role="admin"
        )

    return organizations


@pytest.fixture(name="test_service")
def fixture_test_service():
    """Fixture to create a test service."""
    return factories.ServiceFactory(
        type="test_service",
        config={
            "usage_metrics_endpoint": "http://localhost:8001/metrics/usage",
            "metrics_auth_token": "test_token_valid",
        },
    )


@pytest.mark.django_db
def test_fetch_usage_metrics_from_service(mock_metrics_server, test_service):
    """Test fetching metrics from service with pagination."""
    # Fetch metrics from mock server
    metrics_data = fetch_usage_metrics_from_service(test_service)

    # Verify we got all metrics
    assert len(metrics_data) == 40

    # Verify pagination worked (should have made 2 requests: 100 + 54)
    # Check that metrics are properly structured
    first_metric = metrics_data[0]
    assert "account" in first_metric
    assert "type" in first_metric["account"]
    assert "id" in first_metric["account"]
    assert "metrics" in first_metric

    # Check metrics structure
    metrics = first_metric["metrics"]
    assert "storage_used" in metrics


@pytest.mark.django_db
def test_fetch_usage_metrics_from_service_with_filters(
    mock_metrics_server, test_service
):
    """Test fetching metrics from service with account filters."""
    metrics_data = fetch_usage_metrics_from_service(
        test_service, filters={"account_type": "user", "account_id": "xyz"}
    )

    assert metrics_data == [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
            },
            "metrics": {"storage_used": 2147483648},
        }
    ]


@pytest.mark.django_db
def test_store_service_metrics(mock_metrics_server, test_service, test_organizations):
    """Test storing fetched metrics in the database."""
    # Fetch metrics first
    metrics_data = fetch_usage_metrics_from_service(test_service)
    assert len(metrics_data) == 40

    # Store metrics
    metrics_stored = store_service_metrics(test_service, metrics_data)

    # Verify metrics were stored (40 account * 1 metric = 40 metrics)
    assert metrics_stored == 40

    # Check that metrics exist in database
    stored_metrics = models.Metric.objects.filter(service=test_service)

    storage_used_metrics = stored_metrics.filter(key="storage_used")
    assert storage_used_metrics.count() == 40

    # Make sure we have 40 distinct account combinations
    # Group by account_type, account_id and count the number of distinct accounts
    distinct_accounts = (
        stored_metrics.values("account__type", "account__external_id")
        .annotate(count=Count("*"))
        .distinct()
    )
    assert distinct_accounts.count() == 40


@pytest.mark.django_db
def test_metrics_with_authentication(mock_metrics_server):
    """Test that authentication headers are properly sent."""
    # Create service with auth token
    auth_service = factories.ServiceFactory(
        type="auth_service",
        config={
            "usage_metrics_endpoint": "http://localhost:8001/metrics/usage",
            "metrics_auth_token": "test_token_valid",
        },
    )

    # Fetch metrics (this will test auth headers)
    metrics_data = fetch_usage_metrics_from_service(auth_service)
    assert len(metrics_data) == 40


@pytest.mark.django_db
def test_metrics_storage_with_existing_data(
    mock_metrics_server, test_service, test_organizations
):
    """Test that metrics are properly updated if they already exist."""
    # First, store some metrics
    initial_metrics = [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
            },
            "metrics": {
                "storage_used": 1000,
            },
        }
    ]

    initial_stored = store_service_metrics(test_service, initial_metrics)
    assert initial_stored == 1

    # Verify initial metrics exist
    initial_metrics_db = models.Metric.objects.filter(
        service=test_service, organization=test_organizations["12345678900"]
    )
    assert initial_metrics_db.count() == 1

    initial_storage_used_metric = initial_metrics_db.filter(key="storage_used").first()
    assert initial_storage_used_metric is not None
    initial_value = initial_storage_used_metric.value

    # Now store the same metrics again (should update existing)
    updated_metrics = [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
            },
            "metrics": {
                "storage_used": 2000,
            },
        }
    ]

    updated_stored = store_service_metrics(test_service, updated_metrics)
    assert updated_stored == 1

    # Check that the metrics were updated, not duplicated
    assert models.Metric.objects.filter(service=test_service).count() == 1

    updated_storage_used_metric = models.Metric.objects.filter(
        service=test_service,
        organization=test_organizations["12345678900"],
        key="storage_used",
    ).first()
    assert updated_storage_used_metric.value == 2000
    assert updated_storage_used_metric.value != initial_value


@pytest.mark.django_db
def test_metrics_storage_with_existing_non_usage_metrics_data(
    mock_metrics_server, test_service, test_organizations
):
    """Test that normal metrics don't override usage metrics. And vice versa."""
    # First, store some metrics
    initial_metrics = [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
            },
            "metrics": {
                "storage_used": 1000,
            },
        }
    ]

    initial_stored = store_service_metrics(test_service, initial_metrics)
    assert initial_stored == 1

    # Verify initial metrics exist
    initial_metrics_db = models.Metric.objects.filter(
        service=test_service, organization=test_organizations["12345678900"]
    )
    assert initial_metrics_db.count() == 1

    initial_storage_used_metric = initial_metrics_db.filter(key="storage_used").first()
    assert initial_storage_used_metric is not None

    # Now store normal metrics with the same organization, service and key but different value
    updated_metrics = [
        {
            "siret": "12345678900",
            "metrics": {"storage_used": 2000},
        }
    ]
    updated_stored = store_service_metrics(test_service, updated_metrics)
    assert updated_stored == 1

    # Check that the normal metrics were stored, not overridden by the usage metrics
    assert initial_metrics_db.count() == 2

    metrics = initial_metrics_db.all()
    normal_metric = metrics[0]
    assert normal_metric.key == "storage_used"
    assert normal_metric.value == 2000
    assert normal_metric.account is None

    usage_metric = metrics[1]
    assert usage_metric.key == "storage_used"
    assert usage_metric.value == 1000
    assert usage_metric.account.type == "user"
    assert usage_metric.account.external_id == "xyz"

    # Now store usage metrics again.
    updated_metrics = [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
            },
            "metrics": {
                "storage_used": 3000,
            },
        }
    ]
    initial_stored = store_service_metrics(test_service, updated_metrics)
    assert initial_stored == 1

    # Check that the usage metrics does not override the normal metrics
    assert initial_metrics_db.count() == 2

    metrics = initial_metrics_db.all()
    usage_metric = metrics[0]
    assert usage_metric.key == "storage_used"
    assert usage_metric.value == 3000
    assert usage_metric.account.type == "user"
    assert usage_metric.account.external_id == "xyz"

    normal_metric = metrics[1]
    assert normal_metric.key == "storage_used"
    assert normal_metric.value == 2000
    assert normal_metric.account is None


@pytest.mark.django_db
def test_metrics_with_missing_config():
    """Test handling of services without proper metrics configuration."""
    # Create service without metrics endpoint
    no_config_service = factories.ServiceFactory(type="no_config_service", config={})

    # Should return empty list
    metrics_data = fetch_metrics_from_service(no_config_service)
    assert len(metrics_data) == 0

    # Create service with missing endpoint
    missing_endpoint_service = factories.ServiceFactory(
        type="missing_endpoint_service",
        config={"metrics_auth_token": "test_token_valid"},
    )

    # Should return empty list
    metrics_data = fetch_metrics_from_service(missing_endpoint_service)
    assert len(metrics_data) == 0


@pytest.mark.django_db
def test_metrics_error_handling():
    """Test that errors during fetching are handled gracefully."""
    # Create service with invalid endpoint
    invalid_service = factories.ServiceFactory(
        type="invalid_service",
        config={
            "metrics_endpoint": "http://localhost:9999/nonexistent",
            "metrics_auth_token": "test_token_valid",
        },
    )

    # Should return empty list due to connection error
    metrics_data = fetch_metrics_from_service(invalid_service)
    assert len(metrics_data) == 0


@pytest.mark.django_db
def test_metrics_error_handling_with_invalid_token(mock_metrics_server):
    """Test that errors during fetching are handled gracefully."""
    # Create service with invalid endpoint
    invalid_service = factories.ServiceFactory(
        type="invalid_service",
        config={
            "metrics_endpoint": "http://localhost:8001/metrics",
            "metrics_auth_token": "test_token_invalid",
        },
    )

    # Should return empty list due to connection error
    metrics_data = fetch_metrics_from_service(invalid_service)
    assert len(metrics_data) == 0


@pytest.mark.django_db
def test_metrics_storage_update_existing_account_attributes(
    mock_metrics_server, test_service, test_organizations
):
    """Test that updating the account attributes (email only) froms /metrics works correctly."""
    # First, store some metrics
    initial_metrics = [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
            },
            "metrics": {
                "storage_used": 1000,
            },
        }
    ]

    initial_stored = store_service_metrics(test_service, initial_metrics)
    assert initial_stored == 1

    # Verify initial metrics exist
    metrics = models.Metric.objects.all()
    assert len(metrics) == 1
    initial_storage_used_metric = metrics[0]
    assert initial_storage_used_metric.key == "storage_used"
    assert initial_storage_used_metric.value == 1000
    assert initial_storage_used_metric.account is not None
    account = initial_storage_used_metric.account
    assert account.type == "user"
    assert account.external_id == "xyz"
    assert account.email == ""

    # Now add email to the account from /metrics
    new_metrics = [
        {
            "siret": "12345678900",
            "account": {
                "type": "user",
                "id": "xyz",
                "email": "test@example.com",
            },
            "metrics": {
                "storage_used": 1000,
            },
        }
    ]
    store_service_metrics(test_service, new_metrics)

    # Verify that the account attributes were updated
    metrics = models.Metric.objects.all()
    assert len(metrics) == 1
    new_storage_used_metric = metrics[0]
    assert new_storage_used_metric.key == "storage_used"
    assert new_storage_used_metric.value == 1000
    assert new_storage_used_metric.account is not None
    account = new_storage_used_metric.account
    assert account.type == "user"
    assert account.external_id == "xyz"
    assert account.email == "test@example.com"
