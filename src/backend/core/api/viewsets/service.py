"""
Core model viewsets for the API.
"""

from django.http import HttpResponse

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from core import models
from core.api import serializers


class ServiceViewSet(viewsets.ModelViewSet):
    """ViewSet for Service model."""

    queryset = models.Service.objects.all()
    permission_classes = [IsAuthenticated]

    filterset_fields = ["is_active", "type"]
    search_fields = ["type", "description"]
    ordering_fields = ["type", "created_at"]
    ordering = ["type"]

    @action(
        detail=True,
        methods=["post"],
        url_path="check-subscription",
        url_name="check-subscription",
    )
    def check_subscription(self, request, **kwargs):
        """
        Check if an organization has an active subscription to this service.

        This endpoint allows services to check if a SIRET, SIREN, or INSEE code
        has access to their service.
        """
        # Get the service
        service = self.get_object()

        # Validate organization identifier using serializer
        serializer = serializers.OrganizationIdentifierSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "has_subscription": False,
                    "error_message": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Get organization using serializer (requires identifier for this endpoint)
            organization = serializer.get_organization()

            if organization is None:
                return Response(
                    {
                        "has_subscription": False,
                        "error_message": "No organization identifier provided",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check for subscription
            subscription = (
                models.ServiceSubscription.objects.filter(
                    organization=organization, service=service
                )
                .select_related("organization")
                .first()
            )

            if subscription:
                # Organization has an active subscription
                response_data = {
                    "has_subscription": True,
                    "organization_id": organization.id,
                    "organization_name": organization.name,
                    "subscription_id": subscription.id,
                    "service_id": service.id,
                    "service_name": service.name,
                    "error_message": None,
                }
                return Response(response_data, status=status.HTTP_200_OK)

            # Organization exists but no subscription
            response_data = {
                "has_subscription": False,
                "organization_id": organization.id,
                "organization_name": organization.name,
                "subscription_id": None,
                "service_id": service.id,
                "service_name": service.name,
                "error_message": "Organization exists but has no subscription to this service",
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response(
                {
                    "has_subscription": False,
                    "error_message": str(e),
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        except (ValueError, KeyError, TypeError) as e:
            return Response(
                {
                    "has_subscription": False,
                    "error_message": f"Unexpected error: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ServiceLogoViewSet(viewsets.ReadOnlyModelViewSet):
    """Public ViewSet for serving service logos as SVG files."""

    queryset = models.Service.objects.filter(is_active=True, logo_svg__isnull=False)
    permission_classes = [AllowAny]
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        """
        Serve the service logo as an SVG file with proper headers.
        """
        service = self.get_object()

        if not service.logo_svg:
            return Response(
                {"detail": "Logo not found for this service"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Create response with SVG content
        response = HttpResponse(
            service.logo_svg, content_type="image/svg+xml; charset=utf-8"
        )

        # Set appropriate headers for SVG files
        response["Content-Disposition"] = 'inline; filename="logo.svg"'
        response["Cache-Control"] = "public, max-age=3600"  # Cache for 1 hour
        response["Access-Control-Allow-Origin"] = "*"  # Allow CORS for public access

        return response
