"""
API endpoints for Service model.
"""

from django.db.models import Prefetch, Q
from django.http import HttpResponse

from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.authentication import ExternalManagementApiKeyAuthentication

from .. import permissions, serializers


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

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/
        Return the list of services including the subscription for the given organization
        based on the user's permissions.
    """

    queryset = models.Service.objects.all()
    serializer_class = serializers.OrganizationServiceSerializer
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission,
    ]

    def get_queryset(self):
        organization_id = self.kwargs["organization_id"]
        operator_id = self.kwargs["operator_id"]

        return (
            models.Service.objects.filter(
                Q(
                    subscriptions__organization_id=organization_id,
                    subscriptions__operator_id=operator_id,
                )
                | Q(operatorserviceconfig__operator_id=operator_id)
            )
            .prefetch_related(
                Prefetch(
                    "subscriptions",
                    queryset=models.ServiceSubscription.objects.filter(
                        organization_id=organization_id, operator_id=operator_id
                    ),
                ),
                Prefetch(
                    "operatorserviceconfig_set",
                    queryset=models.OperatorServiceConfig.objects.filter(
                        operator_id=operator_id,
                    ),
                ),
            )
            .distinct()
            .order_by("id")
        )

    def get_serializer_context(self):
        """Add operator_id and organization to serializer context."""
        context = super().get_serializer_context()
        context["operator_id"] = self.kwargs["operator_id"]
        try:
            organization = models.Organization.objects.get(
                id=self.kwargs["organization_id"]
            )
        except models.Organization.DoesNotExist as err:
            raise NotFound("Organization not found.") from err
        context["organization"] = organization
        return context


class OrganizationServiceSubscriptionViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganizationServiceSubscription model.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Get the subscription for the given organization and service.

    PATCH /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Create or update the subscription for the given organization and service.
        Creates the subscription if it doesn't exist (upsert behavior).

    DELETE /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Delete the subscription for the given organization and service.

    Supports both user authentication and external API key authentication.
    """

    queryset = models.ServiceSubscription.objects.all()
    serializer_class = serializers.ServiceSubscriptionSerializer
    authentication_classes = [
        ExternalManagementApiKeyAuthentication,
    ] + [*api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission,
    ]

    def get_queryset(self):
        return models.ServiceSubscription.objects.filter(
            organization=self.kwargs["organization_id"],
            service=self.kwargs["service_id"],
            operator=self.kwargs["operator_id"],
        )

    def get_object(self):
        """
        Get the subscription for the operator-organization-service triple.
        Since there can only be one subscription per operator-organization-service triple,
        we return it directly without requiring a pk in the URL.
        """
        queryset = self.get_queryset()
        try:
            return queryset.get()
        except models.ServiceSubscription.DoesNotExist as err:
            raise NotFound(
                "Subscription not found for this operator-organization-service triple."
            ) from err

    def list(self, request, *args, **kwargs):
        """
        List method is not implemented for this viewset.
        Use retrieve() to get the subscription for the operator-organization-service triple.
        """
        return Response(
            {"detail": "Method not allowed. Use GET to retrieve the subscription."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def retrieve(self, request, *args, **kwargs):
        """
        Return the subscription for the operator-organization-service triple.
        """
        subscription = self.get_object()
        serializer = self.get_serializer(subscription)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update or create the subscription for the operator-organization-service triple.
        Creates the subscription if it doesn't exist (upsert behavior).
        """
        queryset = self.get_queryset()
        subscription = queryset.first()

        organization = models.Organization.objects.get(
            id=self.kwargs["organization_id"]
        )
        service = models.Service.objects.get(id=self.kwargs["service_id"])
        operator = models.Operator.objects.get(id=self.kwargs["operator_id"])

        # Validate request data
        serializer = self.get_serializer(subscription, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        if subscription:
            # Update existing subscription
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Create new subscription with provided data, using defaults for missing fields
        is_active = serializer.validated_data.get("is_active", True)
        metadata = serializer.validated_data.get("metadata", {})
        subscription = models.ServiceSubscription.objects.create(
            organization=organization,
            service=service,
            operator=operator,
            is_active=is_active,
            metadata=metadata,
        )
        return Response(
            self.get_serializer(subscription).data, status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        """
        Delete the subscription for the operator-organization-service triple.
        """
        subscription = self.get_object()
        subscription.delete()
        return Response({}, status=status.HTTP_204_NO_CONTENT)
