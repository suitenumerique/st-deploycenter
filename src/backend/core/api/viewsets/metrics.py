"""Metrics API viewsets."""

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api import permissions


# pylint: disable=abstract-method
class SubscriptionsByServiceSerializer(serializers.Serializer):
    """Validate query params for subscriptions-by-service endpoint."""

    service_type = serializers.CharField(required=False)
    service_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if not attrs.get("service_type") and not attrs.get("service_id"):
            raise serializers.ValidationError(
                "Either service_type or service_id is required."
            )
        return attrs


class SubscriptionsByServiceView(APIView):
    """Return active subscriptions for a given service with hardcoded metrics."""

    authentication_classes = []
    permission_classes = [permissions.MetricsApiKeyPermission]

    def get(self, request):
        """List distinct SIRETs with active subscriptions for a service."""
        serializer = SubscriptionsByServiceSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        filters = {
            "service_subscriptions__is_active": True,
            "siret__isnull": False,
        }
        if serializer.validated_data.get("service_id"):
            filters["service_subscriptions__service__id"] = serializer.validated_data[
                "service_id"
            ]
        if serializer.validated_data.get("service_type"):
            filters["service_subscriptions__service__type"] = serializer.validated_data[
                "service_type"
            ]

        sirets = (
            models.Organization.objects.filter(**filters)
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
