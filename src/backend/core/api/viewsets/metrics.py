"""Metrics API viewsets."""

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api import permissions


# pylint: disable=abstract-method
class SubscriptionsByServiceTypeSerializer(serializers.Serializer):
    """Validate query params for subscriptions-by-service-type endpoint."""

    service_type = serializers.CharField(required=True)


class SubscriptionsByServiceTypeView(APIView):
    """Return active subscriptions for a given service type with hardcoded metrics."""

    authentication_classes = []
    permission_classes = [permissions.MetricsApiKeyPermission]

    def get(self, request):
        """List distinct SIRETs with active subscriptions for a service type."""
        serializer = SubscriptionsByServiceTypeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        service_type = serializer.validated_data["service_type"]

        sirets = (
            models.Organization.objects.filter(
                service_subscriptions__service__type=service_type,
                service_subscriptions__is_active=True,
                siret__isnull=False,
            )
            .exclude(siret="")
            .values_list("siret", flat=True)
            .distinct()
        )

        results = [{"siret": siret, "metrics": {"tu": 1}} for siret in sirets]

        return Response(
            {
                "count": len(results),
                "results": results,
            }
        )
