"""Custom authentication classes for the deploycenter core app"""

import secrets

from django.conf import settings

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from core import models


class ServerToServerAuthentication(BaseAuthentication):
    """
    Custom authentication class for server-to-server requests.
    Validates the presence and correctness of the Authorization header.
    """

    AUTH_HEADER = "Authorization"
    TOKEN_TYPE = "Bearer"  # noqa S105

    def authenticate(self, request):
        """
        Authenticate the server-to-server request by validating the Authorization header.

        This method checks if the Authorization header is present in the request, ensures it
        contains a valid token with the correct format, and verifies the token against the
        list of allowed server-to-server tokens. If the header is missing, improperly formatted,
        or contains an invalid token, an AuthenticationFailed exception is raised.

        Returns:
            None: If authentication is successful
                  (no user is authenticated for server-to-server requests).

        Raises:
            AuthenticationFailed: If the Authorization header is missing, malformed,
            or contains an invalid token.
        """
        auth_header = request.headers.get(self.AUTH_HEADER)
        if not auth_header:
            raise AuthenticationFailed("Authorization header is missing.")

        # Validate token format and existence
        auth_parts = auth_header.split(" ")
        if len(auth_parts) != 2 or auth_parts[0] != self.TOKEN_TYPE:
            raise AuthenticationFailed("Invalid authorization header.")

        token = auth_parts[1]
        # Use constant-time comparison to prevent timing attacks
        if not any(
            secrets.compare_digest(token, allowed_token)
            for allowed_token in settings.SERVER_TO_SERVER_API_TOKENS
        ):
            raise AuthenticationFailed("Invalid server-to-server token.")

        # Authentication is successful, but no user is authenticated

    def authenticate_header(self, request):
        """Return the WWW-Authenticate header value."""
        return f"{self.TOKEN_TYPE} realm='Create item server to server'"


class ExternalManagementApiKeyAuthentication(BaseAuthentication):
    """
    Custom authentication class for external management API requests.
    Validates the external_management_api_key from Operator.config.
    """

    AUTH_HEADER = "Authorization"
    TOKEN_TYPE = "Bearer"  # noqa S105

    def authenticate(self, request):
        """
        Authenticate the external management API request by validating the Authorization header
        against the external_management_api_key stored in Operator.config.

        This method checks if the Authorization header is present in the request, ensures it
        contains a valid token with the correct format, and verifies the token against the
        external_management_api_key in the Operator's config.

        Returns:
            tuple: (None, operator) if authentication is successful, where operator is the
                   Operator instance that owns the API key.
            None: If the request doesn't match this authentication method (allows fallback to
                  other authentication classes).

        Raises:
            AuthenticationFailed: If the Authorization header is present but invalid,
            or if authentication is attempted but fails.
        """
        auth_header = request.headers.get(self.AUTH_HEADER)
        if not auth_header:
            return None

        # Validate token format
        auth_parts = auth_header.split(" ")
        if len(auth_parts) != 2 or auth_parts[0] != self.TOKEN_TYPE:
            return None

        token = auth_parts[1]

        # Get operator_id from URL path
        if not hasattr(request, "resolver_match") or not request.resolver_match:
            return None

        try:
            operator = models.Operator.objects.get(
                config__external_management_api_key=token
            )
        except models.Operator.DoesNotExist:
            return None

        # Authentication is successful, return (None, operator) to store operator in request
        return (None, operator)

    def authenticate_header(self, request):
        """Return the WWW-Authenticate header value."""
        return f"{self.TOKEN_TYPE} realm='External management API'"
