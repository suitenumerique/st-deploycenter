# pylint: disable=invalid-name,too-many-lines
"""
Test users API endpoints in the deploycenter core app.

This one does not test entitlements for a specific service, but rather the entitlements list endpoint
in general, and how it deals with different scenarios such as error handling, etc.

For service-specific entitlements tests, see test_entitlements_{service_name}.py files.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

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
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

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
    assert data["organization"] == {
        "type": organization.type,
        "name": organization.name,
        "oidc_valid": None,
    }
    assert data["operator"] is None
    assert data["entitlements"] == {
        "can_access": False,
        "can_access_reason": AccessEntitlementResolver.Reason.NOT_ACTIVATED,
    }
    assert len(data["potentialOperators"]) == 1
    assert data["potentialOperators"][0]["name"] == operator.name

    expected_url = (
        f"https://suiteterritoriale.anct.gouv.fr/bienvenue/"
        f"{organization.siret}/contact"
        f"?operator={operator.id}&services={service.id}"
    )
    assert data["potentialOperators"][0]["signupUrl"] == expected_url


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
        "organization": None,
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
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator, is_active=False
    )

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
    assert data["operator"] is None
    assert data["entitlements"] == {
        "can_access": False,
        "can_access_reason": AccessEntitlementResolver.Reason.NOT_ACTIVATED,
    }
    assert len(data["potentialOperators"]) == 1
    assert data["potentialOperators"][0]["name"] == operator.name

    assert "signupUrl" in data["potentialOperators"][0]


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
        account=None,
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
        account=None,
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
        == "/metrics/usage?account_type=user&account_id_value=xyz&limit=1000&offset=0"
    )
    assert (
        BuggyServiceServer.requests_received[0]["headers"]["Authorization"]
        == "Bearer test_token"
    )


def test_entitlement_account_organization_mismatch():
    """Test that ValidationError is raised when account organization doesn't match service_subscription organization."""
    operator = factories.OperatorFactory()
    organization1 = factories.OrganizationFactory()
    organization2 = factories.OrganizationFactory()

    service = factories.ServiceFactory()
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization1,
        service=service,
        operator=operator,
    )

    # Create an account with a different organization
    account = factories.AccountFactory(organization=organization2)

    # Create an entitlement with mismatched organizations
    entitlement = models.Entitlement(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="user",
        account=account,
    )

    # Validation should fail
    with pytest.raises(ValidationError) as exc_info:
        entitlement.save()

    assert "account" in exc_info.value.error_dict
    assert "organization must match" in str(exc_info.value.error_dict["account"][0])

    assert models.Entitlement.objects.count() == 0


def test_entitlement_account_type_mismatch():
    """Test that ValidationError is raised when account type doesn't match entitlement account_type."""
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()

    service = factories.ServiceFactory()
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
    )

    # Create an account with type "mailbox"
    account = factories.AccountFactory(organization=organization, type="mailbox")

    # Create an entitlement with account_type "user" (mismatch)
    entitlement = models.Entitlement(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        account_type="user",
        account=account,
    )

    # Validation should fail
    with pytest.raises(ValidationError) as exc_info:
        entitlement.save()

    assert "account" in exc_info.value.error_dict
    assert "type must match" in str(exc_info.value.error_dict["account"][0])

    assert models.Entitlement.objects.count() == 0


def test_api_entitlements_oidc_valid_true(webhook_server):
    """Test oidc_valid is True when idp_id matches an active proconnect subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        rpnt=["1.1", "1.2", "2.1", "2.2"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": f"http://localhost:{port}/metrics/usage",
            "metrics_auth_token": "test_token",
        },
    )

    proconnect_service = factories.ServiceFactory(
        type="proconnect",
        config={"idp_id": "my-idp"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=proconnect_service,
        operator=operator,
        is_active=True,
        metadata={"domains": ["commune.fr"]},
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
            "idp_id": "my-idp",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["organization"]["oidc_valid"] is True


def test_api_entitlements_oidc_valid_false(webhook_server):
    """Test oidc_valid is False when idp_id doesn't match any active proconnect subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        rpnt=["1.1", "1.2", "2.1", "2.2"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": f"http://localhost:{port}/metrics/usage",
            "metrics_auth_token": "test_token",
        },
    )

    proconnect_service = factories.ServiceFactory(
        type="proconnect",
        config={"idp_id": "my-idp"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=proconnect_service,
        operator=operator,
        is_active=True,
        metadata={"domains": ["commune.fr"]},
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
            "idp_id": "wrong-idp",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["organization"]["oidc_valid"] is False


def test_api_entitlements_oidc_valid_inactive_subscription(webhook_server):
    """Test oidc_valid is False when proconnect subscription exists but is inactive."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": f"http://localhost:{port}/metrics/usage",
            "metrics_auth_token": "test_token",
        },
    )

    proconnect_service = factories.ServiceFactory(
        type="proconnect",
        config={"idp_id": "my-idp"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=proconnect_service,
        operator=operator,
        is_active=False,
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
            "idp_id": "my-idp",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["organization"]["oidc_valid"] is False


def test_api_entitlements_oidc_valid_none_without_idp_id(webhook_server):
    """Test oidc_valid is None when no idp_id is passed."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": f"http://localhost:{port}/metrics/usage",
            "metrics_auth_token": "test_token",
        },
    )

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
    assert response.json()["organization"]["oidc_valid"] is None


# pylint: disable=too-many-locals
def test_api_entitlements_oidc_valid_none_for_other_org_type(webhook_server):
    """Test oidc_valid stays None for organization type 'other' even with idp_id."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        type="other",
        adresse_messagerie="contact@other.fr",
        site_internet="https://www.other.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": f"http://localhost:{port}/metrics/usage",
            "metrics_auth_token": "test_token",
        },
    )

    proconnect_service = factories.ServiceFactory(
        type="proconnect",
        config={"idp_id": "my-idp"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=proconnect_service,
        operator=operator,
        is_active=True,
        metadata={"domains": ["other.fr"]},
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
            "idp_id": "my-idp",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["organization"]["oidc_valid"] is None


def test_api_entitlements_query_count_no_subscription():
    """Test that the entitlements endpoint uses a bounded number of queries
    when there is no active subscription (simplest path)."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    organization = factories.OrganizationFactory(siret="12345678900001")

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
        },
    )

    # Warm up any caches (content types, sessions, etc.)
    client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )

    with CaptureQueriesContext(connection) as ctx:
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
    # Expected queries:
    # 1. Session lookup
    # 2. Permission: Service lookup by id (reused by view)
    # 3. Organization lookup by siret
    # 4. ServiceSubscription lookup (org + service) with select_related(operator)
    # 5. Potential operators lookup (OperatorServiceConfig with annotations)
    assert len(ctx) <= 5, f"Expected at most 5 queries, got {len(ctx)}:\n" + "\n".join(
        f"  {i + 1}. {q['sql']}" for i, q in enumerate(ctx)
    )


def test_api_entitlements_query_count_no_subscription_with_idp_id():
    """Test query count when idp_id is provided (adds oidc_valid check)."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    organization = factories.OrganizationFactory(siret="12345678900001")

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
        },
    )

    # Warm up
    client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
            "idp_id": "some-idp",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )

    with CaptureQueriesContext(connection) as ctx:
        response = client.get(
            "/api/v1.0/entitlements/",
            query_params={
                "service_id": service.id,
                "account_type": "user",
                "account_id": "xyz",
                "siret": organization.siret,
                "idp_id": "some-idp",
            },
            headers={"X-Service-Auth": "Bearer test_token"},
        )

    assert response.status_code == 200
    # Same as above + 1 oidc_valid EXISTS query
    assert len(ctx) <= 6, f"Expected at most 6 queries, got {len(ctx)}:\n" + "\n".join(
        f"  {i + 1}. {q['sql']}" for i, q in enumerate(ctx)
    )


def test_api_entitlements_query_count_with_subscription():
    """Test query count with an active subscription (full entitlement resolution path,
    but no metrics endpoint configured to avoid HTTP calls)."""
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
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={"max_storage": 1000},
        account_type="user",
        account=None,
    )

    # Warm up
    client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )

    with CaptureQueriesContext(connection) as ctx:
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
    # Expected queries:
    # 1. Session lookup
    # 2. Permission: Service lookup (reused by view)
    # 3. Organization lookup
    # 4. ServiceSubscription with select_related(operator)
    # 5. Entitlements for subscription (with account JOIN)
    # 6. Metric lookup for entitlement resolution
    # 7. Admin resolver: Account.find_by_identifiers
    # 8. Admin resolver: account.service_links check (if account found)
    assert len(ctx) <= 9, f"Expected at most 9 queries, got {len(ctx)}:\n" + "\n".join(
        f"  {i + 1}. {q['sql']}" for i, q in enumerate(ctx)
    )


# --- potentialOperators tests ---


def _make_entitlements_request(client, service, siret):
    """Helper to make an entitlements API request."""
    return client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )


def _make_service(**kwargs):
    """Helper to create a service with entitlements_api_key."""
    config = {"entitlements_api_key": "test_token"}
    config.update(kwargs.pop("config", {}))
    return factories.ServiceFactory(config=config, **kwargs)


def test_api_entitlements_potential_operators_via_org_role():
    """Operator found via OperatorOrganizationRole + OperatorServiceConfig."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    service = _make_service()

    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    factories.OperatorServiceConfigFactory(
        operator=operator, service=service, display_priority=10
    )

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert data["operator"] is None
    assert len(data["potentialOperators"]) == 1

    pot_op = data["potentialOperators"][0]
    assert pot_op["name"] == operator.name
    assert pot_op["siret"] == operator.siret
    assert pot_op["url"] == operator.url
    assert "hasOrganizationRole" not in pot_op
    assert "hasDepartementMatch" not in pot_op
    assert pot_op["signupUrl"] == (
        f"https://suiteterritoriale.anct.gouv.fr/bienvenue/"
        f"{organization.siret}/contact"
        f"?operator={operator.id}&services={service.id}"
    )


def test_api_entitlements_potential_operators_dept_fallback_commune():
    """Operator found via departement match for commune (no org role)."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory(config={"departements": ["75"]})
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        type="commune",
        departement_code_insee="75",
    )
    service = _make_service()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert data["operator"] is None
    assert len(data["potentialOperators"]) == 1
    assert data["potentialOperators"][0]["name"] == operator.name
    assert data["potentialOperators"][0]["name"] == operator.name
    assert "signupUrl" in data["potentialOperators"][0]


def test_api_entitlements_potential_operators_dept_fallback_epci():
    """Operator found via departement match for EPCI."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory(config={"departements": ["33"]})
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        type="epci",
        departement_code_insee="33",
    )
    service = _make_service()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert len(data["potentialOperators"]) == 1
    assert len(data["potentialOperators"]) == 1


def test_api_entitlements_potential_operators_dept_fallback_departement():
    """Operator found via departement match for departement-type org."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory(config={"departements": ["2A"]})
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        type="departement",
        departement_code_insee="2A",
    )
    service = _make_service()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert len(data["potentialOperators"]) == 1
    assert len(data["potentialOperators"]) == 1


def test_api_entitlements_potential_operators_no_fallback_region():
    """Departement fallback does NOT apply for regions."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory(config={"departements": ["75"]})
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        type="region",
        departement_code_insee="75",
    )
    service = _make_service()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert data["potentialOperators"] == []


def test_api_entitlements_potential_operators_empty_no_service_config():
    """OperatorOrganizationRole exists but no OperatorServiceConfig → empty list."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    service = _make_service()

    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    # No OperatorServiceConfig created

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert data["potentialOperators"] == []


def test_api_entitlements_potential_operators_empty_no_match():
    """No org role and no departement match → empty list."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory(config={"departements": ["75"]})
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        departement_code_insee="33",
    )
    service = _make_service()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert data["potentialOperators"] == []


def test_api_entitlements_potential_operators_ordered_by_priority():
    """Multiple operators via org role, ordered by display_priority DESC."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator_low = factories.OperatorFactory(name="Low Priority Op")
    operator_high = factories.OperatorFactory(name="High Priority Op")
    organization = factories.OrganizationFactory(siret="12345678900001")
    service = _make_service()

    factories.OperatorOrganizationRoleFactory(
        operator=operator_low, organization=organization
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator_high, organization=organization
    )
    factories.OperatorServiceConfigFactory(
        operator=operator_low, service=service, display_priority=5
    )
    factories.OperatorServiceConfigFactory(
        operator=operator_high, service=service, display_priority=20
    )

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert len(data["potentialOperators"]) == 2
    assert data["potentialOperators"][0]["name"] == "High Priority Op"
    assert data["potentialOperators"][1]["name"] == "Low Priority Op"


def test_api_entitlements_potential_operators_combined():
    """One operator via org role, another via departement fallback.

    Org role operator should come first regardless of display_priority.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator_role = factories.OperatorFactory(name="Role Operator")
    operator_dept = factories.OperatorFactory(
        name="Dept Operator",
        config={"departements": ["75"]},
    )
    organization = factories.OrganizationFactory(
        siret="12345678900001",
        type="commune",
        departement_code_insee="75",
    )
    service = _make_service()

    factories.OperatorOrganizationRoleFactory(
        operator=operator_role, organization=organization
    )
    factories.OperatorServiceConfigFactory(
        operator=operator_role, service=service, display_priority=1
    )
    factories.OperatorServiceConfigFactory(
        operator=operator_dept, service=service, display_priority=100
    )

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert len(data["potentialOperators"]) == 2
    # Org role operator comes first even with lower display_priority
    assert data["potentialOperators"][0]["name"] == "Role Operator"
    assert data["potentialOperators"][1]["name"] == "Dept Operator"


def test_api_entitlements_no_potential_operators_with_active_subscription(
    webhook_server,
):
    """Active subscription → potentialOperators key absent, operator set."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    port = webhook_server.server_address[1]
    service = _make_service(
        config={
            "usage_metrics_endpoint": f"http://localhost:{port}/metrics/usage",
            "metrics_auth_token": "test_token",
        },
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.DRIVE_STORAGE,
        config={"max_storage": 1000},
        account_type="user",
        account=None,
    )

    response = _make_entitlements_request(client, service, organization.siret)
    assert response.status_code == 200
    data = response.json()

    assert data["operator"] is not None
    assert data["operator"]["name"] == operator.name
    assert "potentialOperators" not in data
