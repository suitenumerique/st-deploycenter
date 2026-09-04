"""Deploy Center core API endpoints"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError

import sentry_sdk
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework import views as drf_views
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.services.proconnect import DOMAIN_NOT_ALLOWED_ERROR, ProConnectPartnersError

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    """Handle Django ValidationError as an accepted exception.

    For the parameters, see ``exception_handler``
    This code comes from twidi's gist:
    https://gist.github.com/twidi/9d55486c36b6a51bdcb05ce3a763e79f
    """
    # A failed ProConnect push rolls back the change (raised in-transaction); tell
    # the user why rather than returning an opaque 500.
    if isinstance(exc, ProConnectPartnersError):
        # api-partenaires rejects the push (422) when a domain isn't in its
        # allowlist yet — a specific, non-transient, actionable case: name the
        # domains and point at the allowlist sync rather than "retry".
        if exc.error_code == DOMAIN_NOT_ALLOWED_ERROR:
            logger.warning("ProConnect rejected domains %s: %s", exc.domains, exc)
            sentry_sdk.capture_exception(exc)
            domains = ", ".join(exc.domains) if exc.domains else ""
            detail = (
                f"Le(s) domaine(s) {domains} ne sont pas encore autorisés par "
                "ProConnect. Leur pré-validation est en cours et peut prendre "
                "jusqu'à une semaine. Veuillez réessayer plus tard."
            )
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        logger.error("ProConnect synchronization failed: %s", exc, exc_info=exc)
        sentry_sdk.capture_exception(exc)
        return Response(
            {
                "detail": (
                    "La synchronisation des domaines avec ProConnect a échoué. "
                    "La modification a été annulée, veuillez réessayer."
                )
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, ValidationError):
        detail = None
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        elif hasattr(exc, "message"):
            detail = exc.message
        elif hasattr(exc, "messages"):
            detail = exc.messages

        exc = drf_exceptions.ValidationError(detail=detail)

    return drf_views.exception_handler(exc, context)


# pylint: disable=unused-argument
@api_view(["GET"])
def get_frontend_configuration(request):
    """Returns the frontend configuration dict as configured in settings."""
    frontend_configuration = {
        "LANGUAGE_CODE": settings.LANGUAGE_CODE,
    }
    frontend_configuration.update(settings.FRONTEND_CONFIGURATION)
    return Response(frontend_configuration)
