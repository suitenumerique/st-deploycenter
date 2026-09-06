"""Authentication middlewares for the deploycenter core app."""

import logging

from django.conf import settings
from django.contrib import auth

from core.authentication.backends import (
    MFA_ACR_SESSION_KEY,
    OIDCAuthenticationBackend,
)

logger = logging.getLogger(__name__)

OIDC_BACKEND_PATH = (
    f"{OIDCAuthenticationBackend.__module__}.{OIDCAuthenticationBackend.__qualname__}"
)


class RequireMFAMiddleware:
    """Close the OIDC sessions that were not authenticated with a second factor.

    The backend only checks the acr claim when a user logs in, so turning
    OIDC_REQUIRE_MFA on would leave the sessions opened before that untouched
    until they expire (SESSION_COOKIE_AGE). This ends them on their next
    request, which also covers narrowing OIDC_MFA_ACR_VALUES later on.

    Sessions opened another way are left alone: a staff member logging into the
    Django admin with a password never gets an acr claim, and API calls
    authenticated with a bearer token carry no session at all.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.OIDC_REQUIRE_MFA and self.is_session_without_mfa(request):
            logger.info("Ending a session opened without multi-factor authentication")
            auth.logout(request)

        return self.get_response(request)

    @staticmethod
    def is_session_without_mfa(request):
        """Whether the request carries an OIDC session missing an accepted acr.

        Reads the session directly rather than request.user, which would fetch
        the user from the database on every request.
        """
        session = getattr(request, "session", None)

        if session is None:
            return False

        if session.get(auth.BACKEND_SESSION_KEY) != OIDC_BACKEND_PATH:
            return False

        return session.get(MFA_ACR_SESSION_KEY) not in settings.OIDC_MFA_ACR_VALUES
