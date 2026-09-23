"""API ViewSet for sharing some public settings."""

from django.conf import settings

import rest_framework as drf
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny


class ConfigView(drf.views.APIView):
    """API ViewSet for sharing some public settings."""

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["config"],
        responses={
            200: OpenApiResponse(
                description="A dictionary of public configuration settings.",
                response={
                    "type": "object",
                    "properties": {
                        "ENVIRONMENT": {"type": "string", "readOnly": True},
                        "LANGUAGES": {
                            "type": "array",
                            "items": {"type": "string"},
                            "readOnly": True,
                        },
                        "LANGUAGE_CODE": {"type": "string", "readOnly": True},
                    },
                    "required": ["ENVIRONMENT", "LANGUAGES", "LANGUAGE_CODE"],
                },
            )
        },
        description="Return a dictionary of public settings for the frontend to consume.",
    )
    def get(self, request):
        """
        GET /api/v1.0/config/
            Return a dictionary of public settings.
        """
        return drf.response.Response(
            {
                "ENVIRONMENT": settings.ENVIRONMENT,
                "LANGUAGES": settings.LANGUAGES,
                "LANGUAGE_CODE": settings.LANGUAGE_CODE,
            }
        )
