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
        if not token:
            raise AuthenticationFailed("Invalid server-to-server token.")

        # Use constant-time comparison to prevent timing attacks. Falsy entries are
        # skipped: ListValue already drops them when parsing the environment, but
        # compare_digest("", "") is True, so one reaching this list from anywhere
        # else would turn an empty bearer token into a valid credential.
        if not any(
            secrets.compare_digest(token, allowed_token)
            for allowed_token in settings.SERVER_TO_SERVER_API_TOKENS
            if allowed_token
        ):
            raise AuthenticationFailed("Invalid server-to-server token.")

        # Authentication is successful, but no user is authenticated

    def authenticate_header(self, request):
        """Return the WWW-Authenticate header value."""
        return f"{self.TOKEN_TYPE} realm='Create item server to server'"


class ExternalManagementApiKeyAuthentication(BaseAuthentication):
    """
    Base authentication class for external management API requests.
    Looks up an external_management_api_key field on a model instance.
    Subclasses set `model` and `realm`.
    """

    AUTH_HEADER = "Authorization"
    TOKEN_TYPE = "Bearer"  # noqa S105
    model = None
    realm = "External management API"

    def authenticate(self, request):
        auth_header = request.headers.get(self.AUTH_HEADER)
        if not auth_header:
            return None

        auth_parts = auth_header.split(" ")
        if len(auth_parts) != 2 or auth_parts[0] != self.TOKEN_TYPE:
            return None

        # Belt and braces. Nothing stores "" in this field today — the admin saves
        # NULL, because CharField.formfield() sets empty_value=None when the field is
        # null=True, and NULL never matches the lookup below. But a row holding ""
        # (a fixture, a bulk update, a hand-written import) would be authenticated by
        # an empty bearer token, so refuse one outright rather than rely on that.
        token = auth_parts[1]
        if not token:
            return None

        if not hasattr(request, "resolver_match") or not request.resolver_match:
            return None

        try:
            instance = self.model.objects.get(external_management_api_key=token)
        except self.model.DoesNotExist:
            return None

        return (None, instance)

    def authenticate_header(self, request):
        return f"{self.TOKEN_TYPE} realm='{self.realm}'"


class OperatorExternalManagementApiKeyAuthentication(
    ExternalManagementApiKeyAuthentication
):
    """Validates external_management_api_key from Operator."""

    model = models.Operator
    realm = "Operator external management API"


class ServiceExternalManagementApiKeyAuthentication(
    ExternalManagementApiKeyAuthentication
):
    """Validates external_management_api_key from Service."""

    model = models.Service
    realm = "Service external management API"
