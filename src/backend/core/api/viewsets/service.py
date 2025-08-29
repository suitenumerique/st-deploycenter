"""
Core model viewsets for the API.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import models


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

        This endpoint allows services to check if a SIRET or INSEE code
        has access to their service.
        """
        # Get the service
        service = self.get_object()

        # Get siret or insee from request data
        siret = request.data.get("siret")
        insee = request.data.get("insee")

        if not siret and not insee:
            return Response(
                {
                    "has_subscription": False,
                    "error_message": 'Must provide either "siret" or "insee"',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if siret and insee:
            return Response(
                {
                    "has_subscription": False,
                    "error_message": 'Cannot provide both "siret" and "insee"',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Find organization by siret or insee
            if siret:
                # Validate SIRET format (14 digits)
                if not (len(siret) == 14 and siret.isdigit()):
                    return Response(
                        {
                            "has_subscription": False,
                            "error_message": "Invalid SIRET format. Must be 14 digits.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                organization = models.Organization.objects.filter(siret=siret).first()
            else:  # insee
                # Validate INSEE format (5 digits)
                if not (len(insee) == 5 and insee.isdigit()):
                    return Response(
                        {
                            "has_subscription": False,
                            "error_message": "Invalid INSEE format. Must be 5 digits.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                organization = models.Organization.objects.filter(
                    code_insee=insee
                ).first()

            if not organization:
                identifier_value = siret or insee
                identifier_type = "siret" if siret else "insee"
                return Response(
                    {
                        "has_subscription": False,
                        "error_message": f"Organization not found with {identifier_type}: {identifier_value}",
                    },
                    status=status.HTTP_404_NOT_FOUND,
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
                    "service_name": service.type,
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
                "service_name": service.type,
                "error_message": "Organization exists but has no subscription to this service",
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except (ValueError, KeyError, TypeError) as e:
            return Response(
                {
                    "has_subscription": False,
                    "error_message": f"Unexpected error: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
