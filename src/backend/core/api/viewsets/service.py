"""
API endpoints for Service model.
"""

from django.db.models import F, Prefetch, Q
from django.http import HttpResponse

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.settings import api_settings

from core import models
from core.authentication import ExternalManagementApiKeyAuthentication

from .. import permissions, serializers


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Service model."""

    queryset = models.Service.objects.all()
    serializer_class = serializers.ServiceSerializer
    permission_classes = [permissions.IsAuthenticatedWithAnyMethod]

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
                    "has_subscription": subscription.is_active,
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
        permissions.ParentOrganizationAccessPermission,
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
                        service_id__in=F("service_id"),
                    ),
                ),
            )
            .distinct()
            .order_by("id")
        )

    def get_serializer_context(self):
        """Add operator_id to serializer context."""
        context = super().get_serializer_context()
        context["operator_id"] = self.kwargs["operator_id"]
        return context


class OrganizationServiceSubscriptionViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganizationServiceSubscription model.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Get the subscription for the given organization and service.

    POST /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Create a new subscription for the given organization and service.

    PUT /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Update the subscription for the given organization and service.

    PATCH /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Partial update the subscription for the given organization and service.

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
        permissions.ParentOrganizationAccessPermission,
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
        except models.ServiceSubscription.DoesNotExist:
            raise NotFound("Subscription not found for this operator-organization-service triple.")

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

    def create(self, request, *args, **kwargs):
        """
        Create a new subscription for the operator-organization-service triple.
        Returns 400 if subscription already exists.
        """
        if self.get_queryset().exists():
            return Response(
                {"error": "Subscription already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organization = models.Organization.objects.get(
            id=self.kwargs["organization_id"]
        )
        service = models.Service.objects.get(id=self.kwargs["service_id"])
        operator = models.Operator.objects.get(id=self.kwargs["operator_id"])

        subscription = models.ServiceSubscription.objects.create(
            organization=organization, service=service, operator=operator
        )

        serializer = self.get_serializer(subscription)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """
        Delete the subscription for the operator-organization-service triple.
        """
        subscription = self.get_object()
        subscription.delete()
        return Response({}, status=status.HTTP_204_NO_CONTENT)
