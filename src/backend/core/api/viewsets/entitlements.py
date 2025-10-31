"""
Entitlements API viewsets.
"""

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
    service_subscription_id = serializers.UUIDField(required=True)
    account_type = serializers.CharField(required=True)
    account_id = serializers.CharField(required=True)

class EntitlementView(APIView):
    """
    Entitlement view.
    """

    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """
        Get entitlements.
        """

        serializer = EntitlementViewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        service_subscription = models.ServiceSubscription.objects.filter(id=serializer.validated_data["service_subscription_id"]).first()
        if not service_subscription:
            raise drf.exceptions.NotFound("Service subscription not found. Make sure the service has been enabled.")

        operator_data = OperatorSerializer(service_subscription.operator).data
        entitlements = models.Entitlement.objects.filter(service_subscription=service_subscription)

        entitlements_data = {}
        for entitlement in entitlements:
            resolver = get_entitlement_resolver(entitlement.type)
            entitlement_data = resolver.resolve(entitlement, service_subscription, {
                "account_type": serializer.validated_data["account_type"],
                "account_id": serializer.validated_data["account_id"],
            })
            entitlements_data = {**entitlements_data, **entitlement_data}

        user = request.user
        return Response({
            "operator": operator_data,
            "entitlements": entitlements_data
        })