"""
Lagaufre API endpoint for retrieving services with subscription status for organizations.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from core import models
from core.api import serializers


class LagaufreViewSet(viewsets.ViewSet):
    """
    ViewSet for the Lagaufre endpoint that returns services with subscription status.

    This public endpoint allows anyone to retrieve a list of all services
    with their subscription status, ordered by subscribed services first.
    No authentication required.
    """

    permission_classes = [AllowAny]

    @action(
        detail=False,
        methods=["get"],
        url_path="services",
        url_name="services",
    )
    def get_services_with_subscription_status(self, request):
        """
        Return a list of services with their subscription status for an organization.

        Query parameters (optional):
        - siret: SIRET code (14 digits)
        - siren: SIREN code (9 digits)
        - insee: INSEE code (5 digits)

        If no organization identifier is provided, returns all services without
        subscription information (organization-less mode).

        Returns services ordered by subscription status (subscribed first) when
        organization is provided, or by name when no organization is provided.
        """
        # Validate organization identifier using serializer
        serializer = serializers.OrganizationIdentifierSerializer(
            data=request.query_params
        )

        if not serializer.is_valid():
            return Response(
                {
                    "error": serializer.errors,
                    "services": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get organization (returns None if no identifier provided)
        try:
            organization = serializer.get_organization()
        except ValidationError as e:
            return Response(
                {"error": str(e), "services": []},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get all active services
        services = models.Service.objects.filter(is_active=True).order_by("name")

        response_data = {}

        # Get subscription IDs if organization provided
        subscription_ids = None
        if organization is not None:
            subscription_ids = set(
                models.ServiceSubscription.objects.filter(
                    organization=organization
                ).values_list("service_id", flat=True)
            )
            response_data["organization"] = {
                "name": organization.name,
                "type": organization.type,
                "siret": organization.siret,
            }

        response_data["services"] = self._build_services_data(
            services, subscription_ids
        )

        response = Response(response_data, headers={"Access-Control-Allow-Origin": "*"})

        return response

    def _build_services_data(self, services, subscription_ids):
        """Build services data with optional subscription information."""

        # Organization mode: ordered by subscription status
        subscribed_services = []
        unsubscribed_services = []

        for service in services:
            service_data = {
                "id": service.id,
                "name": service.name,
                "url": service.url,
                "maturity": service.maturity,
                "logo": service.get_logo_url(),
            }

            if subscription_ids is not None:
                service_data["subscribed"] = service.id in subscription_ids

            if subscription_ids is not None and service.id in subscription_ids:
                subscribed_services.append(service_data)
            else:
                unsubscribed_services.append(service_data)

        return subscribed_services + unsubscribed_services
