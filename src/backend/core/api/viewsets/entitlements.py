"""
Entitlements API viewsets.
"""

from core.entitlements.resolvers.access_entitlement_resolver import AccessEntitlementResolver
from core.entitlements.resolvers import get_entitlement_resolver
from core.api.serializers import OperatorSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers
import rest_framework as drf

from core import models
from core.api import permissions


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

        # # Authentication.
        # api_key_header = request.headers.get("X-Service-Auth")
        # if not api_key_header:
        #     raise drf.exceptions.AuthenticationFailed("API key is required.")

        # api_key = api_key_header.split(" ")[1]

        # service_auth = models.Service.objects.filter(api_key=api_key).first()
        # if not service_auth:
        #     raise drf.exceptions.AuthenticationFailed("Invalid API key.")

        serializer = EntitlementViewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        # service_subscription = models.ServiceSubscription.objects.filter(id=serializer.validated_data["service_subscription_id"]).first()
        # if not service_subscription:
        #     raise drf.exceptions.NotFound("Service subscription not found. Make sure the service has been enabled.")

        organization = models.Organization.objects.filter(siret=serializer.validated_data["siret"]).first()
        if not organization:
            raise drf.exceptions.NotFound("Organization not found. Make sure the organization exists.")

        service = models.Service.objects.filter(id=serializer.validated_data["service_id"]).first()
        if not service:
            raise drf.exceptions.NotFound("Service not found. Make sure the service exists.")
        
        # We should always have one or none service subscription for an organization-service pair.
        service_subscription = models.ServiceSubscription.objects.filter(organization=organization, service=service).first()

        # Response building.

        operator_data = None
        entitlement_context = {
            "account_type": serializer.validated_data["account_type"],
            "account_id": serializer.validated_data["account_id"],
            "organization": organization,
            "service": service,
            "service_subscription": service_subscription,
        }

        # This entitlement should always be resolved.
        entitlements_data = {**AccessEntitlementResolver().resolve(entitlement_context)}

        if service_subscription:
            operator_data = OperatorSerializer(service_subscription.operator).data
            entitlements = models.Entitlement.objects.filter(service_subscription=service_subscription)
            print(entitlements)
            
            for entitlement in entitlements:
                resolver = get_entitlement_resolver(entitlement.type)
                entitlement_data = resolver.resolve(entitlement_context)
                entitlements_data = {**entitlements_data, **entitlement_data}

        return Response({
            "operator": operator_data,
            "entitlements": entitlements_data
        })