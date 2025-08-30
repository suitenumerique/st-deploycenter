"""
Tests for metrics scraping functionality with fake HTTP server.
"""

# pylint: disable=unused-argument

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

from core import factories, models
from core.tasks.metrics import fetch_metrics_from_service, store_service_metrics


class MockMetricsServer(BaseHTTPRequestHandler):
    """Mock HTTP server that serves paginated metrics data."""

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET requests with pagination support."""
        if self.path.startswith("/metrics"):
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

            # Generate mock metrics data in the expected format
            total_count = 40  # Total orgs available
            start_idx = offset
            end_idx = min(offset + limit, total_count)

            # Create metrics for this page
            metrics = []
            for org_idx in range(start_idx, end_idx):
                # Alternate between SIRET and INSEE identifiers
                if org_idx % 2 == 0:
                    identifier = {"siret": f"123456789{org_idx:02d}"}
                else:
                    identifier = {"insee": f"750{org_idx:02d}"}

                # Generate realistic metric values
                metrics.append(
                    {
                        **identifier,
                        "metrics": {
                            "tu": 1000 + (org_idx * 10) % 2000,  # Total users
                            "yau": 100 + (org_idx * 5) % 500,  # Yearly active users
                            "mau": 50 + (org_idx * 3) % 200,  # Monthly active users
                            "wau": 10 + (org_idx * 2) % 100,  # Weekly active users
                        },
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

    # Create organizations with INSEE codes
    for i in range(40):
        insee = f"750{i:02d}"
        org = factories.OrganizationFactory(
            code_insee=insee,
            name=f"Test Organization INSEE {i + 1}",
            departement_code_insee="75",  # Paris department
            region_code_insee="11",  # Île-de-France region
        )
        organizations[insee] = org

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
            "metrics_endpoint": "http://localhost:8001/metrics",
            "metrics_auth_token": "test_token_valid",
        },
    )


@pytest.mark.django_db
def test_fetch_metrics_from_service(mock_metrics_server, test_service):
    """Test fetching metrics from service with pagination."""
    # Fetch metrics from mock server
    metrics_data = fetch_metrics_from_service(test_service)

    # Verify we got all metrics
    assert len(metrics_data) == 40

    # Verify pagination worked (should have made 2 requests: 100 + 54)
    # Check that metrics are properly structured
    first_metric = metrics_data[0]
    assert "siret" in first_metric
    assert "metrics" in first_metric

    # Check metrics structure
    metrics = first_metric["metrics"]
    assert "tu" in metrics
    assert "yau" in metrics
    assert "mau" in metrics
    assert "wau" in metrics

    # Check that we have metrics for different organizations
    org_identifiers = set()
    for metric in metrics_data:
        if "siret" in metric:
            org_identifiers.add(metric["siret"])
        if "insee" in metric:
            org_identifiers.add(metric["insee"])

    assert len(org_identifiers) == 40


@pytest.mark.django_db
def test_store_service_metrics(mock_metrics_server, test_service, test_organizations):
    """Test storing fetched metrics in the database."""
    # Fetch metrics first
    metrics_data = fetch_metrics_from_service(test_service)
    assert len(metrics_data) == 40

    # Store metrics
    metrics_stored = store_service_metrics(test_service, metrics_data)

    # Verify metrics were stored (40 orgs * 4 metric types = 160 metrics)
    assert metrics_stored == 160

    # Check that metrics exist in database
    stored_metrics = models.Metric.objects.filter(service=test_service)

    tu_metrics = stored_metrics.filter(key="tu")
    yau_metrics = stored_metrics.filter(key="yau")
    mau_metrics = stored_metrics.filter(key="mau")
    wau_metrics = stored_metrics.filter(key="wau")

    assert tu_metrics.count() == 40
    assert yau_metrics.count() == 40
    assert mau_metrics.count() == 40
    assert wau_metrics.count() == 40
    assert stored_metrics.count() == 160


@pytest.mark.django_db
def test_metrics_with_authentication(mock_metrics_server):
    """Test that authentication headers are properly sent."""
    # Create service with auth token
    auth_service = factories.ServiceFactory(
        type="auth_service",
        config={
            "metrics_endpoint": "http://localhost:8001/metrics",
            "metrics_auth_token": "test_token_valid",
        },
    )

    # Fetch metrics (this will test auth headers)
    metrics_data = fetch_metrics_from_service(auth_service)
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
            "metrics": {"tu": 1000, "yau": 100, "mau": 50, "wau": 10},
        }
    ]

    initial_stored = store_service_metrics(test_service, initial_metrics)
    assert initial_stored == 4  # 4 metric types

    # Verify initial metrics exist
    initial_metrics_db = models.Metric.objects.filter(
        service=test_service, organization=test_organizations["12345678900"]
    )
    assert initial_metrics_db.count() == 4

    initial_tu_metric = initial_metrics_db.filter(key="tu").first()
    assert initial_tu_metric is not None
    initial_value = initial_tu_metric.value

    # Now store the same metrics again (should update existing)
    updated_metrics = [
        {
            "siret": "12345678900",
            "metrics": {
                "tu": 2000,  # Different value
                "yau": 200,
                "mau": 100,
                "wau": 20,
            },
        }
    ]

    updated_stored = store_service_metrics(test_service, updated_metrics)
    assert updated_stored == 4

    # Check that the metrics were updated, not duplicated
    assert models.Metric.objects.filter(service=test_service).count() == 4

    updated_tu_metric = models.Metric.objects.filter(
        service=test_service,
        organization=test_organizations["12345678900"],
        key="tu",
    ).first()
    assert updated_tu_metric.value == 2000
    assert updated_tu_metric.value != initial_value


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
