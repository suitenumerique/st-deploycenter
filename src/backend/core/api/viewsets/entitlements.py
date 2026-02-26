"""
Entitlements API viewsets.
"""

from django.db.models import Q

import rest_framework as drf
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api import permissions
from core.api.serializers import OperatorSerializer
from core.entitlements.resolvers import (
    get_access_entitlement_resolver,
    get_admin_entitlement_resolver,
    get_entitlement_resolver,
)
from core.entitlements.resolvers.entitlement_resolver import (
    get_context_account_unique_identifier,
    get_entitlements_by_priority,
)
from core.tasks.metrics import scrape_service_usage_metrics


class EntitlementOperatorSerializer(OperatorSerializer):
    """
    Serialize operators for entitlements, with some fields removed.
    """

    class Meta(OperatorSerializer.Meta):
        fields = [
            f
            for f in OperatorSerializer.Meta.fields
            if f not in ("user_role", "is_active")
        ]


# pylint: disable=abstract-method
class EntitlementViewSerializer(serializers.Serializer):
    """
    Entitlement view serializer.
    """

    # service_subscription_id = serializers.UUIDField(required=True)
    account_type = serializers.CharField(required=True)
    account_id = serializers.CharField(required=False)
    account_email = serializers.EmailField(required=False)
    siret = serializers.CharField(required=True)
    service_id = serializers.IntegerField(required=True)

    def validate(self, attrs):
        """
        Validate that at least one of account_id or account_email is provided.
        """
        account_id = attrs.get("account_id")
        account_email = attrs.get("account_email")

        if not account_id and not account_email:
            raise serializers.ValidationError(
                "Either 'account_id' or 'account_email' must be provided."
            )

        return attrs


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
        account_id = serializer.validated_data.get("account_id")
        account_email = serializer.validated_data.get("account_email")

        operator_data = None
        entitlement_context = {
            "account_type": account_type,
            "account_id": account_id,
            "account_email": account_email,
            "organization": organization,
            "service": service,
            "service_subscription": service_subscription,
            "siret": siret,
        }

        # This entitlement should always be resolved.
        entitlements_data = {
            **get_access_entitlement_resolver(service).resolve(entitlement_context)
        }

        if service_subscription and service_subscription.is_active:
            operator_data = EntitlementOperatorSerializer(
                service_subscription.operator
            ).data

            unique_identifier, unique_identifier_value = (
                get_context_account_unique_identifier(entitlement_context)
            )
            # Get the entitlements for the given service subscription.
            # Also include the override entitlement for the given account if it exists.
            # Q(account=None) makes sure we don't include override from other accounts.
            entitlements = models.Entitlement.objects.filter(
                service_subscription=service_subscription,
            ).filter(
                Q(account=None)
                | Q(**{f"account__{unique_identifier}": unique_identifier_value})
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
                scrape_filters = {
                    "account_type": account_type,
                }
                if account_id:
                    scrape_filters["account_id"] = account_id
                if account_email:
                    scrape_filters["account_email"] = account_email
                scrape_service_usage_metrics(service, scrape_filters)
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

            # Resolve admin entitlement.
            entitlements_data = {
                **entitlements_data,
                **get_admin_entitlement_resolver(service).resolve(entitlement_context),
            }

        # Separate metric fields from entitlements.
        metrics_data = {}
        for key in ("storage_used",):
            if key in entitlements_data:
                metrics_data[key] = entitlements_data.pop(key)

        response_data = {"operator": operator_data, "entitlements": entitlements_data}
        if metrics_data:
            response_data["metrics"] = metrics_data
        return Response(response_data)
