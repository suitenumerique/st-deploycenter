"""
Webhook library for sending HTTP requests to configured endpoints.
Handles ServiceSubscription lifecycle events with configurable templates and content types.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from django.utils import timezone

import requests

logger = logging.getLogger(__name__)


class WebhookError(Exception):
    """Raised when webhook delivery fails."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_text: Optional[str] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(self.message)


class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize webhook configuration.

        Args:
            config: Dictionary containing webhook configuration
        """
        self.url = config.get("url")
        if not self.url:
            raise ValueError("Webhook URL is required")

        # Validate URL format
        try:
            parsed = urlparse(self.url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid URL format")
        except Exception as e:
            raise ValueError(f"Invalid URL format: {e}") from e

        self.method = config.get("method", "POST").upper()
        if self.method not in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            raise ValueError(f"Unsupported HTTP method: {self.method}")

        self.body_template = config.get("body", {})
        self.headers_template = config.get("headers", {})
        self.timeout = config.get("timeout", 10)

    def render_body(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Render the webhook body template with provided context.

        Args:
            context_data: Data to use for template rendering

        Returns:
            Rendered body as a dictionary
        """
        if not self.body_template:
            return {}

        try:
            return self._render_template_object(self.body_template, context_data)
        except Exception as e:
            logger.error("Failed to render webhook body template: %s", str(e))
            raise WebhookError(f"Template rendering failed: {e}") from e

    def render_headers(self, context_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Render the webhook headers template with provided context.

        Args:
            context_data: Data to use for template rendering

        Returns:
            Rendered headers as a dictionary
        """
        if not self.headers_template:
            return {}

        try:
            rendered = self._render_template_object(self.headers_template, context_data)
            # Ensure all header values are strings
            return {key: str(value) for key, value in rendered.items()}
        except Exception as e:
            logger.error("Failed to render webhook headers template: %s", str(e))
            raise WebhookError(f"Headers template rendering failed: {e}") from e

    def _render_template_object(
        self, template_obj: Any, context_data: Dict[str, Any]
    ) -> Any:
        """
        Recursively render template variables in a JSON-like object structure.
        Uses MongoDB-like syntax: {"$val": "context_key"} for simple value extraction.

        Args:
            template_obj: The template object (dict, list, string, etc.)
            context_data: Data to use for template rendering

        Returns:
            Rendered object with template variables replaced
        """
        if isinstance(template_obj, dict):
            # Check if this is a value extraction object with $val key
            if "$val" in template_obj and len(template_obj) == 1:
                # This is a value extraction: {"$val": "context_key"}
                context_key = template_obj["$val"]
                if isinstance(context_key, str):
                    # Direct access to flat context
                    return context_data.get(context_key)
                # If not a string, raise an error
                raise ValueError(
                    f"$val must be a string, got {type(context_key).__name__}: {context_key}"
                )
            if "$tpl" in template_obj and len(template_obj) == 1:
                # This is a template string: {"$tpl": "Hello {{name}}"}
                template_string = template_obj["$tpl"]
                if isinstance(template_string, str):
                    return self._render_template_string(template_string, context_data)
                # If not a string, raise an error
                raise ValueError(
                    f"$tpl must be a string, got {type(template_string).__name__}: {template_string}"
                )
            # Regular dict - render each key-value pair
            return {
                key: self._render_template_object(value, context_data)
                for key, value in template_obj.items()
            }
        if isinstance(template_obj, list):
            return [
                self._render_template_object(item, context_data)
                for item in template_obj
            ]
        if isinstance(template_obj, str):
            # Plain strings are returned as-is (no automatic template rendering)
            return template_obj

        # For numbers, booleans, None, etc., return as-is
        return template_obj

    def _render_template_string(
        self, template_string: str, context_data: Dict[str, Any]
    ) -> str:
        """
        Render a template string with simple {{variable}} substitution.

        Args:
            template_string: Template string with {{variable}} placeholders
            context_data: Data to use for template rendering

        Returns:
            Rendered string with variables replaced
        """

        def replace_var(match):
            var_name = match.group(1)
            return str(context_data.get(var_name, ""))

        # Replace {{variable}} with values from context
        return re.sub(r"\{\{(\w+)\}\}", replace_var, template_string)


class WebhookClient:
    """Client for sending webhooks to configured endpoints."""

    def __init__(self, webhook_configs: List[Dict[str, Any]]):
        """
        Initialize webhook client with configurations.

        Args:
            webhook_configs: List of webhook configuration dictionaries
        """
        self.webhook_configs = []
        for config in webhook_configs:
            try:
                webhook_config = WebhookConfig(config)
                self.webhook_configs.append(webhook_config)
            except ValueError as e:
                logger.error("Invalid webhook configuration: %s", str(e))
                # Continue with other valid configurations

    def send_webhooks(
        self,
        event_type: str,
        subscription,
        organization,
        service,
    ) -> List[Dict[str, Any]]:
        """
        Send webhook notifications for a subscription event.

        Args:
            event_type: Type of event (e.g., "subscription.created", "subscription.updated")
            subscription: ServiceSubscription instance
            organization: Organization instance
            service: Service instance

        Returns:
            List of results from each webhook attempt
        """
        results = []
        context_data = {
            "event_type": event_type,
            "timestamp": timezone.now().isoformat(),
            # Subscription data
            "subscription_id": str(subscription.id),
            "subscription_created_at": subscription.created_at.isoformat(),
            "subscription_updated_at": subscription.updated_at.isoformat(),
            "subscription_metadata": subscription.metadata,
            # Organization data
            "organization_id": str(organization.id),
            "organization_name": organization.name,
            "organization_type": organization.type,
            "organization_code_insee": organization.code_insee,
            "organization_code_postal": organization.code_postal,
            "organization_population": organization.population,
            "organization_siret": organization.siret,
            "organization_siren": organization.siren,
            # Service data
            "service_id": service.id,
            "service_name": service.name,
            "service_type": service.type,
            "service_url": service.url,
            "service_description": service.description,
            "service_maturity": service.maturity,
        }

        for webhook_config in self.webhook_configs:
            try:
                result = self._send_single_webhook(webhook_config, context_data)
                results.append(result)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to send webhook to %s: %s", webhook_config.url, str(e)
                )
                status_code = None
                if hasattr(e, "status_code"):
                    status_code = e.status_code
                results.append(
                    {
                        "url": webhook_config.url,
                        "success": False,
                        "error": str(e),
                        "status_code": status_code,
                    }
                )

        return results

    def _send_single_webhook(
        self, webhook_config: WebhookConfig, context_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a single webhook request.

        Args:
            webhook_config: Configuration for this webhook
            context_data: Data to include in the webhook

        Returns:
            Result dictionary with success status and details
        """
        try:
            # Render the body template
            rendered_body = webhook_config.render_body(context_data)

            # Render custom headers template
            custom_headers = webhook_config.render_headers(context_data)

            # Prepare headers (custom headers override defaults)
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "DeployCenter-Webhook/1.0",
                **custom_headers,  # Custom headers override defaults
            }

            # Prepare request data
            request_kwargs = {
                "headers": headers,
                "timeout": webhook_config.timeout,
            }

            # Add body for methods that support it
            if webhook_config.method in ["POST", "PUT", "PATCH"]:
                if rendered_body:
                    # Use the rendered template as the request body
                    request_kwargs["json"] = rendered_body
                else:
                    # Send minimal event data if no template
                    request_kwargs["json"] = {
                        "event_type": context_data["event_type"],
                        "timestamp": context_data["timestamp"],
                    }

            # Make the HTTP request
            logger.info(
                "Sending %s webhook to %s",
                webhook_config.method,
                webhook_config.url,
            )

            response = requests.request(  # noqa: S113
                webhook_config.method,
                webhook_config.url,
                **request_kwargs,
            )

            # Check response status
            response.raise_for_status()

            logger.info(
                "Webhook sent successfully to %s (status: %d)",
                webhook_config.url,
                response.status_code,
            )

            return {
                "url": webhook_config.url,
                "success": True,
                "status_code": response.status_code,
                "response_text": response.text[:500],  # Limit response text length
            }

        except requests.exceptions.Timeout as e:
            logger.error("Webhook timeout for %s: %s", webhook_config.url, str(e))
            raise WebhookError(
                f"Webhook timeout after {webhook_config.timeout}s",
                response_text=str(e),
            ) from e

        except requests.exceptions.RequestException as e:
            logger.error(
                "Webhook request failed for %s: %s", webhook_config.url, str(e)
            )
            status_code = None
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
            raise WebhookError(
                f"Webhook request failed: {e}",
                status_code=status_code,
                response_text=str(e),
            ) from e

        except Exception as e:
            logger.error(
                "Unexpected error sending webhook to %s: %s", webhook_config.url, str(e)
            )
            raise WebhookError(f"Unexpected error: {e}") from e
