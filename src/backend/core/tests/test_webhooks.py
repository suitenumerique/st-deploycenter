# pylint: disable=invalid-name
"""
Tests for webhook functionality in ServiceSubscription lifecycle events.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.models import Organization, Service, ServiceSubscription
from core.webhooks import WebhookClient, WebhookConfig, WebhookError


class MockWebhookServer(BaseHTTPRequestHandler):
    """Mock HTTP server for testing webhook delivery."""

    requests_received = []  # Class variable to store all requests

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

    def _handle_request(self, method: str):
        """Handle any HTTP request."""
        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # Parse JSON body if present
        try:
            body_data = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            body_data = body.decode("utf-8", errors="ignore")

        # Store request information
        request_info = {
            "method": method,
            "path": self.path,
            "headers": dict(self.headers),
            "body": body_data,
        }
        MockWebhookServer.requests_received.append(request_info)

        # Send response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Suppress log messages during testing."""


class SlowWebhookServer(MockWebhookServer):
    """Mock server that responds slowly to test timeouts."""

    def _handle_request(self, method: str):
        """Handle request with artificial delay."""
        time.sleep(2)  # 2 second delay
        super()._handle_request(method)


class FailingWebhookServer(MockWebhookServer):
    """Mock server that returns error responses."""

    def _handle_request(self, method: str):
        """Handle request with error response."""
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "Internal Server Error"}')


@pytest.fixture(name="webhook_server")
def fixture_webhook_server():
    """Fixture providing a mock webhook server."""
    # Clear any previous requests
    MockWebhookServer.requests_received = []

    server = HTTPServer(("localhost", 0), MockWebhookServer)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield server

    server.shutdown()
    server.server_close()


@pytest.fixture(name="slow_webhook_server")
def fixture_slow_webhook_server():
    """Fixture providing a slow mock webhook server."""
    server = HTTPServer(("localhost", 0), SlowWebhookServer)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield server

    server.shutdown()
    server.server_close()


@pytest.fixture(name="failing_webhook_server")
def fixture_failing_webhook_server():
    """Fixture providing a failing mock webhook server."""
    server = HTTPServer(("localhost", 0), FailingWebhookServer)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield server

    server.shutdown()
    server.server_close()


@pytest.fixture(name="sample_organization")
def fixture_sample_organization():
    """Create a sample organization for testing."""
    return Organization.objects.create(
        name="Test Organization",
        type="commune",
        code_insee="12345",
        population=10000,
    )


@pytest.fixture(name="sample_service")
def fixture_sample_service():
    """Create a sample service for testing."""
    return Service.objects.create(
        name="Test Service",
        type="test_service",
        url="https://example.com",
        description="A test service",
        config={
            "webhooks": [
                {
                    "url": "http://localhost:8000/webhook",
                    "method": "POST",
                    "body": {
                        "message": {"$val": "event_type"},
                        "data": {
                            "subscription_id": {"$val": "subscription_id"},
                            "organization_name": {"$val": "organization_name"},
                            "static_field": "This is static",
                        },
                    },
                    "timeout": 10,
                }
            ]
        },
    )


@pytest.fixture(name="sample_subscription")
def fixture_sample_subscription(sample_organization, sample_service):
    """Create a sample subscription for testing."""
    return ServiceSubscription.objects.create(
        organization=sample_organization,
        service=sample_service,
        metadata={"test": "data"},
    )


class TestWebhookConfig:
    """Test webhook configuration validation."""

    def test_valid_config(self):
        """Test valid webhook configuration."""
        config = {
            "url": "https://example.com/webhook",
            "method": "POST",
            "body": {
                "message": {"$val": "event_type"},
                "data": {
                    "subscription_id": {"$val": "subscription_id"},
                    "static_value": "This is static",
                },
            },
            "timeout": 5,
        }
        webhook_config = WebhookConfig(config)

        assert webhook_config.url == "https://example.com/webhook"
        assert webhook_config.method == "POST"
        assert webhook_config.body_template == {
            "message": {"$val": "event_type"},
            "data": {
                "subscription_id": {"$val": "subscription_id"},
                "static_value": "This is static",
            },
        }
        assert webhook_config.timeout == 5

    def test_default_values(self):
        """Test default values for webhook configuration."""
        config = {"url": "https://example.com/webhook"}
        webhook_config = WebhookConfig(config)

        assert webhook_config.method == "POST"
        assert webhook_config.body_template == {}
        assert webhook_config.timeout == 10

    def test_invalid_url(self):
        """Test invalid URL validation."""
        config = {"url": "not-a-url"}
        with pytest.raises(ValueError, match="Invalid URL format"):
            WebhookConfig(config)

    def test_missing_url(self):
        """Test missing URL validation."""
        config = {}
        with pytest.raises(ValueError, match="Webhook URL is required"):
            WebhookConfig(config)

    def test_invalid_method(self):
        """Test invalid HTTP method validation."""
        config = {"url": "https://example.com/webhook", "method": "INVALID"}
        with pytest.raises(ValueError, match="Unsupported HTTP method"):
            WebhookConfig(config)

    def test_template_rendering(self):
        """Test template rendering functionality with $val syntax."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "message": {"$val": "event_type"},
                "data": {
                    "user": {"$val": "name"},
                    "action": {"$val": "event_type"},
                    "timestamp": {"$val": "timestamp"},
                    "static_field": "This is static",
                },
            },
        }
        webhook_config = WebhookConfig(config)

        context = {
            "name": "World",
            "event_type": "created",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        rendered = webhook_config.render_body(context)

        expected = {
            "message": "created",
            "data": {
                "user": "World",
                "action": "created",
                "timestamp": "2024-01-01T00:00:00Z",
                "static_field": "This is static",
            },
        }
        assert rendered == expected

    def test_nested_template_rendering(self):
        """Test nested template rendering with lists and complex structures."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "event": {"$val": "event_type"},
                "organizations": [
                    {
                        "name": {"$val": "organization_name"},
                        "type": {"$val": "organization_type"},
                    },
                    {"name": "Static Org", "type": "commune"},
                ],
                "metadata": {
                    "subscription_id": {"$val": "subscription_id"},
                    "service_name": {"$val": "service_name"},
                    "static_metadata": {"key": "value"},
                },
            },
        }
        webhook_config = WebhookConfig(config)

        context = {
            "event_type": "created",
            "organization_name": "Test City",
            "organization_type": "commune",
            "subscription_id": "123",
            "service_name": "Test Service",
        }
        rendered = webhook_config.render_body(context)

        expected = {
            "event": "created",
            "organizations": [
                {"name": "Test City", "type": "commune"},
                {"name": "Static Org", "type": "commune"},
            ],
            "metadata": {
                "subscription_id": "123",
                "service_name": "Test Service",
                "static_metadata": {"key": "value"},
            },
        }
        assert rendered == expected

    def test_static_strings_not_rendered(self):
        """Test that static strings are not treated as templates."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "static_string": "This is {{ not a template }} {{organization_name}}",
                "template_string": {"$val": "event_type"},
                "mixed": {
                    "static": "Static value",
                    "template": {"$val": "organization_name"},
                },
            },
        }
        webhook_config = WebhookConfig(config)

        context = {"event_type": "created", "organization_name": "Test Org"}
        rendered = webhook_config.render_body(context)

        expected = {
            "static_string": "This is {{ not a template }} {{organization_name}}",  # Should remain unchanged
            "template_string": "created",
            "mixed": {"static": "Static value", "template": "Test Org"},
        }
        assert rendered == expected

    def test_nested_value_extraction(self):
        """Test value extraction from flat context."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "org_name": {"$val": "organization_name"},
                "org_type": {"$val": "organization_type"},
                "service_name": {"$val": "service_name"},
                "subscription_id": {"$val": "subscription_id"},
                "deep_nested": {"$val": "organization_address_city"},
            },
        }
        webhook_config = WebhookConfig(config)

        context = {
            "organization_name": "Test City",
            "organization_type": "commune",
            "service_name": "Test Service",
            "subscription_id": "123",
            "organization_address_city": "Paris",
        }
        rendered = webhook_config.render_body(context)

        expected = {
            "org_name": "Test City",
            "org_type": "commune",
            "service_name": "Test Service",
            "subscription_id": "123",
            "deep_nested": "Paris",
        }
        assert rendered == expected

    def test_missing_nested_value(self):
        """Test handling of missing values."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "existing": {"$val": "organization_name"},
                "missing": {"$val": "organization_missing_field"},
                "deep_missing": {"$val": "organization_address_missing_city"},
            },
        }
        webhook_config = WebhookConfig(config)

        context = {"organization_name": "Test City", "service_name": "Test Service"}
        rendered = webhook_config.render_body(context)

        expected = {"existing": "Test City", "missing": None, "deep_missing": None}
        assert rendered == expected

    def test_invalid_val_type(self):
        """Test that $val with non-string value raises an error."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "invalid_val": {"$val": 123},
            },
        }
        webhook_config = WebhookConfig(config)

        context = {"test": "value"}

        with pytest.raises(WebhookError, match="\\$val must be a string"):
            webhook_config.render_body(context)

    def test_template_string_rendering(self):
        """Test template string rendering with $tpl syntax."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "message": {
                    "$tpl": "Hello {{organization_name}}, event: {{event_type}}"
                },
                "details": {
                    "$tpl": "Subscription {{subscription_id}} for {{service_name}}"
                },
            },
        }
        webhook_config = WebhookConfig(config)

        context = {
            "organization_name": "Test City",
            "event_type": "created",
            "subscription_id": "123",
            "service_name": "Test Service",
        }
        rendered = webhook_config.render_body(context)

        expected = {
            "message": "Hello Test City, event: created",
            "details": "Subscription 123 for Test Service",
        }
        assert rendered == expected

    def test_template_string_missing_variables(self):
        """Test template string with missing variables."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "message": {"$tpl": "Hello {{missing_var}}, event: {{event_type}}"},
            },
        }
        webhook_config = WebhookConfig(config)

        context = {"event_type": "created"}
        rendered = webhook_config.render_body(context)

        expected = {"message": "Hello , event: created"}
        assert rendered == expected

    def test_invalid_tpl_type(self):
        """Test that $tpl with non-string value raises an error."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "invalid_tpl": {"$tpl": 123},
            },
        }
        webhook_config = WebhookConfig(config)

        context = {"test": "value"}

        with pytest.raises(WebhookError, match="\\$tpl must be a string"):
            webhook_config.render_body(context)


class TestWebhookClient:
    """Test webhook client functionality."""

    @pytest.mark.django_db
    def test_send_webhook_success(self, webhook_server, sample_subscription):
        """Test successful webhook delivery."""
        port = webhook_server.server_address[1]
        webhook_configs = [
            {
                "url": f"http://localhost:{port}/webhook",
                "method": "POST",
                "body": {
                    "message": {"$val": "event_type"},
                    "data": {
                        "subscription_id": {"$val": "subscription_id"},
                        "organization": {"$val": "organization_name"},
                        "static_field": "This is static",
                    },
                },
                "timeout": 5,
            }
        ]

        client = WebhookClient(webhook_configs)
        results = client.send_webhooks(
            "created",
            sample_subscription,
            sample_subscription.organization,
            sample_subscription.service,
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["status_code"] == 200

        # Check that the server received the request
        assert len(webhook_server.RequestHandlerClass.requests_received) == 1
        request = webhook_server.RequestHandlerClass.requests_received[0]
        assert request["method"] == "POST"
        assert request["path"] == "/webhook"
        assert request["body"]["message"] == "created"
        assert request["body"]["data"]["subscription_id"] == str(sample_subscription.id)
        assert (
            request["body"]["data"]["organization"]
            == sample_subscription.organization.name
        )
        assert request["body"]["data"]["static_field"] == "This is static"

    @pytest.mark.django_db
    def test_send_webhook_timeout(self, slow_webhook_server, sample_subscription):
        """Test webhook timeout handling."""
        port = slow_webhook_server.server_address[1]
        webhook_configs = [
            {
                "url": f"http://localhost:{port}/webhook",
                "method": "POST",
                "timeout": 1,  # 1 second timeout
            }
        ]

        client = WebhookClient(webhook_configs)
        results = client.send_webhooks(
            "created",
            sample_subscription,
            sample_subscription.organization,
            sample_subscription.service,
        )

        assert len(results) == 1
        assert results[0]["success"] is False
        assert "timeout" in results[0]["error"].lower()

    @pytest.mark.django_db
    def test_send_webhook_server_error(
        self, failing_webhook_server, sample_subscription
    ):
        """Test webhook server error handling."""
        port = failing_webhook_server.server_address[1]
        webhook_configs = [
            {
                "url": f"http://localhost:{port}/webhook",
                "method": "POST",
                "timeout": 5,
            }
        ]

        client = WebhookClient(webhook_configs)
        results = client.send_webhooks(
            "created",
            sample_subscription,
            sample_subscription.organization,
            sample_subscription.service,
        )

        assert len(results) == 1
        assert results[0]["success"] is False
        assert results[0]["status_code"] == 500

    @pytest.mark.django_db
    def test_multiple_webhooks(self, webhook_server, sample_subscription):
        """Test sending multiple webhooks."""
        port = webhook_server.server_address[1]
        webhook_configs = [
            {
                "url": f"http://localhost:{port}/webhook1",
                "method": "POST",
                "body": {
                    "webhook": 1,
                    "event": {"$val": "event_type"},
                    "static_field": "Static value",
                },
            },
            {
                "url": f"http://localhost:{port}/webhook2",
                "method": "PUT",
                "body": {
                    "webhook": 2,
                    "event": {"$val": "event_type"},
                    "organization": {"$val": "organization_name"},
                },
            },
        ]

        client = WebhookClient(webhook_configs)
        results = client.send_webhooks(
            "updated",
            sample_subscription,
            sample_subscription.organization,
            sample_subscription.service,
        )

        assert len(results) == 2
        assert all(result["success"] for result in results)

        # Check that both requests were received
        requests = webhook_server.RequestHandlerClass.requests_received
        assert len(requests) == 2

        # Check request paths and bodies
        paths = [req["path"] for req in requests]
        assert "/webhook1" in paths
        assert "/webhook2" in paths

        # Check that each webhook got the correct body
        for request in requests:
            if request["path"] == "/webhook1":
                assert request["body"]["webhook"] == 1
                assert request["body"]["event"] == "updated"
                assert request["body"]["static_field"] == "Static value"
            elif request["path"] == "/webhook2":
                assert request["body"]["webhook"] == 2
                assert request["body"]["event"] == "updated"
                assert (
                    request["body"]["organization"]
                    == sample_subscription.organization.name
                )

    def test_invalid_webhook_config(self):
        """Test handling of invalid webhook configurations."""
        webhook_configs = [
            {"url": "http://localhost:8000/webhook"},  # Valid
            {"url": "invalid-url"},  # Invalid
            {"url": "http://localhost:8000/webhook2"},  # Valid
        ]

        client = WebhookClient(webhook_configs)
        # Should only have 2 valid configurations
        assert len(client.webhook_configs) == 2

    @pytest.mark.django_db
    def test_template_rendering_in_webhook(self, webhook_server, sample_subscription):
        """Test template rendering in webhook body."""
        port = webhook_server.server_address[1]
        webhook_configs = [
            {
                "url": f"http://localhost:{port}/webhook",
                "method": "POST",
                "body": {
                    "organization": {"$val": "organization_name"},
                    "service": {"$val": "service_name"},
                    "event": {"$val": "event_type"},
                    "details": {
                        "org_type": {"$val": "organization_type"},
                        "service_url": {"$val": "service_url"},
                        "static_detail": "This is static",
                    },
                },
            }
        ]

        client = WebhookClient(webhook_configs)
        results = client.send_webhooks(
            "created",
            sample_subscription,
            sample_subscription.organization,
            sample_subscription.service,
        )

        assert results[0]["success"] is True

        request = webhook_server.RequestHandlerClass.requests_received[0]
        assert request["body"]["organization"] == sample_subscription.organization.name
        assert request["body"]["service"] == "Test Service"
        assert request["body"]["event"] == "created"
        assert request["body"]["details"]["org_type"] == "commune"
        assert request["body"]["details"]["service_url"] == "https://example.com"
        assert request["body"]["details"]["static_detail"] == "This is static"

    @pytest.mark.django_db
    def test_minimal_event_data(self, webhook_server, sample_subscription):
        """Test webhook with minimal event data (no template)."""
        port = webhook_server.server_address[1]
        webhook_configs = [
            {
                "url": f"http://localhost:{port}/webhook",
                "method": "POST",
                # No body template
            }
        ]

        client = WebhookClient(webhook_configs)
        results = client.send_webhooks(
            "deleted",
            sample_subscription,
            sample_subscription.organization,
            sample_subscription.service,
        )

        assert results[0]["success"] is True

        request = webhook_server.RequestHandlerClass.requests_received[0]
        body = request["body"]
        assert body["event_type"] == "deleted"
        assert "timestamp" in body


@pytest.mark.django_db
class TestWebhookIntegration:
    """Test webhook integration with Django models and signals."""

    def test_subscription_created_webhook(self, webhook_server, sample_organization):
        """Test webhook sent when subscription is created."""
        port = webhook_server.server_address[1]
        service = Service.objects.create(
            name="Test Service",
            type="test_service",
            url="https://example.com",
            config={
                "webhooks": [
                    {
                        "url": f"http://localhost:{port}/webhook",
                        "method": "POST",
                        "body": {
                            "message": {"$val": "event_type"},
                            "event_type": {"$val": "event_type"},
                            "subscription": {
                                "id": {"$val": "subscription_id"},
                                "organization": {"$val": "organization_name"},
                                "service": {"$val": "service_name"},
                                "static_field": "This is static",
                            },
                        },
                        "timeout": 5,
                    }
                ]
            },
        )

        # Create subscription (this should trigger the webhook)
        ServiceSubscription.objects.create(
            organization=sample_organization,
            service=service,
            metadata={"test": "data"},
        )

        # Give the signal handler time to execute
        time.sleep(0.1)

        # Check that webhook was sent
        requests = webhook_server.RequestHandlerClass.requests_received
        assert len(requests) == 1

        request = requests[0]
        assert request["method"] == "POST"
        assert request["body"]["message"] == "subscription.created"
        assert request["body"]["event_type"] == "subscription.created"
        assert (
            request["body"]["subscription"]["organization"] == sample_organization.name
        )
        assert request["body"]["subscription"]["service"] == service.name
        assert request["body"]["subscription"]["static_field"] == "This is static"

    def test_subscription_updated_webhook(self, webhook_server, sample_subscription):
        """Test webhook sent when subscription is updated."""
        port = webhook_server.server_address[1]
        service = sample_subscription.service
        service.config = {
            "webhooks": [
                {
                    "url": f"http://localhost:{port}/webhook",
                    "method": "POST",
                    "body": {
                        "message": {"$val": "organization_name"},
                        "event_type": {"$val": "event_type"},
                        "changes": {
                            "subscription_id": {"$val": "subscription_id"},
                            "organization": {"$val": "organization_name"},
                        },
                    },
                    "timeout": 5,
                }
            ]
        }
        service.save()

        # Update subscription (this should trigger the webhook)
        sample_subscription.metadata = {"updated": "data"}
        sample_subscription.save()

        # Give the signal handler time to execute
        time.sleep(0.1)

        # Check that webhook was sent
        requests = webhook_server.RequestHandlerClass.requests_received
        assert len(requests) == 1

        request = requests[0]
        assert request["method"] == "POST"
        assert request["body"]["message"] == sample_subscription.organization.name
        assert request["body"]["event_type"] == "subscription.updated"
        assert (
            request["body"]["changes"]["organization"]
            == sample_subscription.organization.name
        )

    def test_subscription_deleted_webhook(self, webhook_server, sample_subscription):
        """Test webhook sent when subscription is deleted."""
        port = webhook_server.server_address[1]
        service = sample_subscription.service
        service.config = {
            "webhooks": [
                {
                    "url": f"http://localhost:{port}/webhook",
                    "method": "POST",
                    "body": {
                        "message": {"$val": "organization_name"},
                        "event_type": {"$val": "event_type"},
                        "deleted_subscription": {
                            "id": {"$val": "subscription_id"},
                            "organization": {"$val": "organization_name"},
                            "service": {"$val": "service_name"},
                        },
                    },
                    "timeout": 5,
                }
            ]
        }
        service.save()

        # Delete subscription (this should trigger the webhook)
        organization_name = sample_subscription.organization.name
        service_name = sample_subscription.service.name
        sample_subscription.delete()

        # Give the signal handler time to execute
        time.sleep(0.1)

        # Check that webhook was sent
        requests = webhook_server.RequestHandlerClass.requests_received
        assert len(requests) == 1

        request = requests[0]
        assert request["method"] == "POST"
        assert request["body"]["message"] == organization_name
        assert request["body"]["event_type"] == "subscription.deleted"
        assert (
            request["body"]["deleted_subscription"]["organization"] == organization_name
        )
        assert request["body"]["deleted_subscription"]["service"] == service_name

    def test_no_webhooks_configured(self, sample_organization):
        """Test that no webhooks are sent when none are configured."""
        service = Service.objects.create(
            name="Test Service",
            type="test_service",
            url="https://example.com",
            config={},  # No webhooks configured
        )

        # Create subscription (should not trigger any webhooks)
        subscription = ServiceSubscription.objects.create(
            organization=sample_organization,
            service=service,
        )

        # Give the signal handler time to execute
        time.sleep(0.1)

        # No webhooks should have been sent (no server to check, but no errors should occur)
        assert subscription.id is not None

    def test_webhook_failure_handling(
        self, failing_webhook_server, sample_organization
    ):
        """Test that webhook failures don't break the application."""
        port = failing_webhook_server.server_address[1]
        service = Service.objects.create(
            name="Test Service",
            type="test_service",
            url="https://example.com",
            config={
                "webhooks": [
                    {
                        "url": f"http://localhost:{port}/webhook",
                        "method": "POST",
                        "timeout": 5,
                    }
                ]
            },
        )

        # Create subscription (should not fail even if webhook fails)
        subscription = ServiceSubscription.objects.create(
            organization=sample_organization,
            service=service,
        )

        # Give the signal handler time to execute
        time.sleep(0.1)

        # Subscription should still be created successfully
        assert subscription.id is not None

    def test_webhook_timeout_handling(self, slow_webhook_server, sample_organization):
        """Test that webhook timeouts don't break the application."""
        port = slow_webhook_server.server_address[1]
        service = Service.objects.create(
            name="Test Service",
            type="test_service",
            url="https://example.com",
            config={
                "webhooks": [
                    {
                        "url": f"http://localhost:{port}/webhook",
                        "method": "POST",
                        "timeout": 1,  # Short timeout
                    }
                ]
            },
        )

        # Create subscription (should not fail even if webhook times out)
        subscription = ServiceSubscription.objects.create(
            organization=sample_organization,
            service=service,
        )

        # Give the signal handler time to execute
        time.sleep(0.1)

        # Subscription should still be created successfully
        assert subscription.id is not None


class TestWebhookErrorHandling:
    """Test webhook error handling scenarios."""

    def test_webhook_error_creation(self):
        """Test WebhookError creation and attributes."""
        error = WebhookError(
            "Test error", status_code=500, response_text="Server Error"
        )

        assert error.message == "Test error"
        assert error.status_code == 500
        assert error.response_text == "Server Error"

    def test_webhook_error_without_details(self):
        """Test WebhookError creation without optional details."""
        error = WebhookError("Simple error")

        assert error.message == "Simple error"
        assert error.status_code is None
        assert error.response_text is None

    def test_template_rendering_error(self):
        """Test template rendering error handling."""
        config = {
            "url": "https://example.com/webhook",
            "body": {
                "message": {"$val": "undefined_variable"},
                "data": {"$val": "another_undefined"},
            },
        }
        webhook_config = WebhookConfig(config)

        # With $val, missing values return None instead of raising errors
        context = {}
        rendered = webhook_config.render_body(context)

        expected = {"message": None, "data": None}
        assert rendered == expected
