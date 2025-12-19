# pylint: disable=invalid-name
"""
Test users API endpoints in the deploycenter core app.

This one does not test entitlements for a specific service, but rather the entitlements list endpoint
in general, and how it deals with different scenarios such as error handling, etc.

For service-specific entitlements tests, see test_entitlements_{service_name}.py files.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db


class MockServiceServer(BaseHTTPRequestHandler):
    """Mock HTTP server for testing webhook delivery."""

    requests_received = []  # Class variable to store all requests
    MOCK_STORAGE_USED = 500

    def do_GET(self):
        """Handle GET requests."""
        self._handle_request("GET")

    def do_POST(self):
        """Handle POST requests."""
        self._handle_request("POST")

    def do_PUT(self):
        """Handle PUT requests."""
        self._handle_request("PUT")

    def do_PATCH(self):
        """Handle PATCH requests."""
        self._handle_request("PATCH")

    def do_DELETE(self):
        """Handle DELETE requests."""
        self._handle_request("DELETE")

    def get_body_data(self):
        """Get the body data from the request."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            return json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body.decode("utf-8", errors="ignore")

    def log_request_received(self, method: str):
        """Log the request received."""
        request_info = {
            "method": method,
            "path": self.path,
            "headers": dict(self.headers),
            "body": self.get_body_data(),
        }
        self.__class__.requests_received.append(request_info)

    def _handle_request(self, method: str):
        """Handle any HTTP request."""

        self.log_request_received(method)
        # Send response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response_data = {
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": self.__class__.MOCK_STORAGE_USED},
                }
            ],
        }
        self.wfile.write(json.dumps(response_data).encode())

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Suppress log messages during testing."""


class BuggyServiceServer(MockServiceServer):
    """Mock HTTP server for testing buggy service."""

    def _handle_request(self, method: str):
        """Handle request with error response."""
        self.log_request_received(method)
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "Internal Server Error"}')


@pytest.fixture(name="webhook_server")
def fixture_webhook_server():
    """Fixture providing a mock webhook server."""
    # Clear any previous requests
    MockServiceServer.requests_received = []

    server = HTTPServer(("localhost", 0), MockServiceServer)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield server

    server.shutdown()
    server.server_close()


@pytest.fixture(name="buggy_service_server")
def fixture_buggy_service_server():
    """Fixture providing a buggy mock service server."""
    # Clear any previous requests
    MockServiceServer.requests_received = []

    server = HTTPServer(("localhost", 0), BuggyServiceServer)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield server

    server.shutdown()
    server.server_close()


def test_api_entitlements_list_anon():
    """Test the entitlements list endpoint for anonymous users."""
    client = APIClient()
    response = client.get("/api/v1.0/entitlements/")
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Informations d'authentification non fournies."
    }


def test_api_entitlements_list_no_subscription(webhook_server):
    """Test the entitlements list endpoint for service without subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    metrics_usage_endpoint = f"http://localhost:{port}/metrics/usage"

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )

    # Test that we can upload to the drive
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
    assert data == {
        "operator": None,
        "entitlements": {
            "can_access": False,
            "can_access_reason": AccessEntitlementResolver.Reason.NOT_ACTIVATED,
        },
    }


def test_api_entitlements_list_organization_not_found(webhook_server):
    """Test the entitlements list endpoint for a siret that does not match any organization."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="A")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    metrics_usage_endpoint = f"http://localhost:{port}/metrics/usage"

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )

    # Test that we can upload to the drive
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": "B",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": None,
        "entitlements": {
            "can_access": False,
            "can_access_reason": AccessEntitlementResolver.Reason.NO_ORGANIZATION,
        },
    }


def test_api_entitlements_list_with_inactive_subscription(webhook_server):
    """Test the entitlements list endpoint for service with inactive subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    metrics_usage_endpoint = f"http://localhost:{port}/metrics/usage"

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )

    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator, is_active=False
    )

    # Test that we can upload to the drive
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
    assert data == {
        "operator": None,
        "entitlements": {
            "can_access": False,
            "can_access_reason": AccessEntitlementResolver.Reason.NOT_ACTIVATED,
        },
    }


def test_api_entitlements_list_service_token_mismatch(webhook_server):  # pylint: disable=unused-argument
    """
    Test the entitlements list token verification.
    The token is valid but for another service, it should return a 403.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
        },
    )

    factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token2",
        },
    )

    # Test that we can upload to the drive
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token2"},
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Vous n'avez pas la permission d'effectuer cette action."
    }


def test_api_entitlements_list_usage_metrics_endpoint_not_reachable():
    """
    Test the entitlements list endpoint error handling.
    The usage metrics endpoint is not reachable.
    It should still return a 200.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    not_used_port = 8765
    metrics_usage_endpoint = f"http://localhost:{not_used_port}/metrics/usage"

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="user",
        account_id="",
    )

    # Test that we can upload to the drive
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
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": False,
            },
        },
    )


def test_api_entitlements_list_usage_metrics_endpoint_error(buggy_service_server):
    """
    Test the entitlements list endpoint error handling.
    The usage metrics endpoint returns an error.
    It should still return a 200.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = buggy_service_server.server_address[1]
    metrics_usage_endpoint = f"http://localhost:{port}/metrics/usage"

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="user",
        account_id="",
    )

    # Test that we can upload to the drive
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
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": False,
            },
        },
    )

    # Metrics endpoint should have been called
    assert len(BuggyServiceServer.requests_received) == 1
    assert BuggyServiceServer.requests_received[0]["method"] == "GET"
    assert (
        BuggyServiceServer.requests_received[0]["path"]
        == "/metrics/usage?account_type=user&account_id=xyz&limit=1000&offset=0"
    )
    assert (
        BuggyServiceServer.requests_received[0]["headers"]["Authorization"]
        == "Bearer test_token"
    )
