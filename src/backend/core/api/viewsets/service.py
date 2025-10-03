"""
API endpoints for Service model.
"""

from django.http import HttpResponse

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core import models
from .. import serializers, permissions
import rest_framework as drf
from django.db.models import Prefetch


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Service model."""

    queryset = models.Service.objects.all()
    serializer_class = serializers.ServiceSerializer
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


class OrganizationServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for OrganizationService model.
    
    GET /api/v1.0/organizations/<organization_id>/services/
        Return the list of services including the subscription for the given organization 
        based on the user's permissions.
    """

    queryset = models.Service.objects.all()
    serializer_class = serializers.OrganizationServiceSerializer
    permission_classes = [IsAuthenticated, permissions.ParentOrganizationAccessPermission]

    def get_queryset(self):
        organization = models.Organization.objects.get(id=self.kwargs['organization_id'])
        prefetch_queryset = models.ServiceSubscription.objects.filter(organization=organization)
        return models.Service.objects.all().prefetch_related(
            Prefetch("subscriptions", queryset=prefetch_queryset)
        ).order_by('created_at')


class OrganizationServiceSubscriptionViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganizationServiceSubscription model.
    
    POST /api/v1.0/organizations/<organization_id>/services/<service_id>/subscription/
        Create a new subscription for the given organization and service.

    DELETE /api/v1.0/organizations/<organization_id>/services/<service_id>/subscription/
        Delete the given subscription for the given organization and service.
    """

    queryset = models.ServiceSubscription.objects.all()
    serializer_class = serializers.ServiceSubscriptionSerializer
    permission_classes = [IsAuthenticated, permissions.ParentOrganizationAccessPermission]

    def get_queryset(self):
        return models.ServiceSubscription.objects.filter(
            organization=self.kwargs['organization_id'], 
            service=self.kwargs['service_id']
        )

    def list(self, request, *args, **kwargs):
        """
        Return the subscription if one exists, otherwise return empty response.
        Since there can only be one subscription per organization-service pair,
        we return the subscription directly instead of a paginated list.
        """
        try:
            subscription = self.get_queryset().get()
            serializer = self.get_serializer(subscription)
            return Response(serializer.data)
        except models.ServiceSubscription.DoesNotExist:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

    def retrieve(self, request, *args, **kwargs):
        """
        Return 404 since individual subscription retrieval is not supported.
        Use the list method to get the subscription for the organization-service pair.
        """
        return Response({}, status=status.HTTP_404_NOT_FOUND)
    
    def update(self, request, *args, **kwargs):
        """
        Update the subscription for the organization-service pair.
        """
        return Response({}, status=status.HTTP_404_NOT_FOUND)

    def create(self, request, *args, **kwargs):
        """
        Create a new subscription for the organization-service pair.
        Returns 400 if subscription already exists.
        """
        if self.get_queryset().exists():
            return Response(
                {'error': 'Subscription already exists'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        organization = models.Organization.objects.get(id=self.kwargs['organization_id'])
        service = models.Service.objects.get(id=self.kwargs['service_id'])
        
        subscription = models.ServiceSubscription.objects.create(
            organization=organization, 
            service=service
        )

        serializer = self.get_serializer(subscription)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """
        Delete the subscription for the organization-service pair.
        """
        subscription = self.get_object()
        if not subscription:
            return Response({}, status=status.HTTP_404_NOT_FOUND)
        subscription.delete()
        return Response({}, status=status.HTTP_204_NO_CONTENT)