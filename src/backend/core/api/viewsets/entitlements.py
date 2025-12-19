"""
Entitlements API viewsets.
"""

import rest_framework as drf
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api import permissions
from core.api.serializers import OperatorSerializer
from core.entitlements.resolvers import get_entitlement_resolver
from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)
from core.entitlements.resolvers.entitlement_resolver import (
    get_entitlements_by_priority,
)
from core.tasks.metrics import scrape_service_usage_metrics


# pylint: disable=abstract-method
class EntitlementViewSerializer(serializers.Serializer):
    """
    Entitlement view serializer.
    """

    # service_subscription_id = serializers.UUIDField(required=True)
    account_type = serializers.CharField(required=True)
    account_id = serializers.CharField(required=True)
    siret = serializers.CharField(required=True)
    service_id = serializers.IntegerField(required=True)


class EntitlementView(APIView):
    """
    Entitlement view.
    """

    permission_classes = [permissions.ServiceAuthenticationPermission]

    def get(self, request):
        """
        Get entitlements.
        """

        serializer = EntitlementViewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        siret = serializer.validated_data["siret"]

        organization = models.Organization.objects.filter(siret=siret).first()

        service = models.Service.objects.filter(
            id=serializer.validated_data["service_id"]
        ).first()
        if not service:
            raise drf.exceptions.NotFound(
                "Service not found. Make sure the service exists."
            )

        service_subscription = None
        if organization:
            # We should always have one or none service subscription for an organization-service pair.
            service_subscription = models.ServiceSubscription.objects.filter(
                organization=organization, service=service
            ).first()

        # Response building.
        account_type = serializer.validated_data["account_type"]
        account_id = serializer.validated_data["account_id"]

        operator_data = None
        entitlement_context = {
            "account_type": account_type,
            "account_id": account_id,
            "organization": organization,
            "service": service,
            "service_subscription": service_subscription,
            "siret": siret,
        }

        # This entitlement should always be resolved.
        entitlements_data = {**AccessEntitlementResolver().resolve(entitlement_context)}

        if service_subscription and service_subscription.is_active:
            operator_data = OperatorSerializer(service_subscription.operator).data
            entitlements = models.Entitlement.objects.filter(
                service_subscription=service_subscription
            )
            entitlements_by_type = {}
            for entitlement in entitlements:
                if entitlement.type not in entitlements_by_type:
                    entitlements_by_type[entitlement.type] = []
                entitlements_by_type[entitlement.type].append(entitlement)

            # Always scrape incoming account metrics. (user, mailbox, etc.)
            scrape_account = True
            # Not all services supports organization account type.
            scrape_organization = False

            # Determine if we need to scrape organization metrics.
            # We scrape organization metrics only if we have at least one organization entitlement.
            for _entitlement_type, entitlements_of_type in entitlements_by_type.items():
                entitlements_by_priority = get_entitlements_by_priority(
                    entitlements_of_type
                )
                if entitlements_by_priority.get("organization"):
                    scrape_organization = True

            # Scrape metrics.
            if scrape_account:
                scrape_service_usage_metrics(
                    service,
                    {
                        "account_type": account_type,
                        "account_id": account_id,
                    },
                )
            if scrape_organization:
                scrape_service_usage_metrics(
                    service,
                    {
                        "account_type": "organization",
                        "account_id": organization.id,
                    },
                )

            # Resolve entitlements.
            for entitlement_type, entitlements_of_type in entitlements_by_type.items():
                resolver = get_entitlement_resolver(entitlement_type)
                entitlement_data = resolver.resolve(
                    {**entitlement_context, "entitlements": entitlements_of_type}
                )
                entitlements_data = {**entitlements_data, **entitlement_data}

        return Response({"operator": operator_data, "entitlements": entitlements_data})
