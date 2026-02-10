"""
API endpoints for Metrics model.
"""

from django.db.models import Avg, Sum

from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.authentication import ExternalManagementApiKeyAuthentication

from .. import permissions, serializers


class OperatorMetricsViewSet(viewsets.ViewSet):
    """ViewSet for Metrics model nested under Operator.

    GET /api/v1.0/operators/<operator_id>/metrics/
        Return the list of metrics for the given operator based on filters.
        Supports filtering by key, service, organizations, accounts, account_type.
        Supports aggregation via agg=sum|avg query param.

    Required query params:
        - key: Metric key to filter on (single value)
        - service: Service ID to filter on (single value)

    Optional query params:
        - organizations: Comma-separated organization IDs. Defaults to all orgs the operator has access to.
        - accounts: Comma-separated account IDs. If omitted, returns all accounts (including null).
        - account_type: Filter by account type (e.g., "user", "mailbox").
        - agg: Aggregation type (sum|avg). If provided, returns aggregated value.
        - group_by: Group results by 'organization'. Returns sum per organization.
    """

    authentication_classes = [
        ExternalManagementApiKeyAuthentication,
    ] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAccessPermission,
    ]

    def _get_operator_organizations(self, operator_id):
        """Get all organization IDs that the operator has access to."""
        return models.Organization.objects.filter(
            operator_roles__operator_id=operator_id
        ).values_list("id", flat=True)

    def _parse_comma_separated_ids(self, param_value):
        """Parse comma-separated IDs from query param."""
        if not param_value:
            return None
        return [id.strip() for id in param_value.split(",") if id.strip()]

    def list(self, request, operator_id=None):
        """List metrics with filtering and optional aggregation."""
        # Validate required params
        key = request.query_params.get("key")
        service_id = request.query_params.get("service")

        if not key:
            return Response(
                {"error": "Query parameter 'key' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not service_id:
            return Response(
                {"error": "Query parameter 'service' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate service exists
        try:
            service = models.Service.objects.get(id=service_id)
        except models.Service.DoesNotExist:
            return Response(
                {"error": f"Service with id '{service_id}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get allowed organizations for this operator (convert UUIDs to strings for comparison)
        allowed_org_ids = set(
            str(org_id) for org_id in self._get_operator_organizations(operator_id)
        )

        # Parse optional organization filter
        org_ids_param = request.query_params.get("organizations")
        if org_ids_param:
            requested_org_ids = set(self._parse_comma_separated_ids(org_ids_param))
            # Filter to only allowed organizations
            org_ids = list(requested_org_ids & allowed_org_ids)
            if not org_ids:
                return Response(
                    {"error": "No valid organizations found for the given IDs."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # Default to all organizations the operator has access to
            org_ids = list(allowed_org_ids)

        # Build base queryset
        queryset = models.Metric.objects.filter(
            key=key,
            service=service,
            organization_id__in=org_ids,
        )

        # Filter by account_type if provided
        account_type = request.query_params.get("account_type")
        if account_type:
            queryset = queryset.filter(account__type=account_type)

        # Filter by accounts if provided
        accounts_param = request.query_params.get("accounts")
        if accounts_param:
            account_ids = self._parse_comma_separated_ids(accounts_param)
            queryset = queryset.filter(account_id__in=account_ids)

        # Handle aggregation
        agg = request.query_params.get("agg")
        if agg:
            if agg not in ("sum", "avg"):
                return Response(
                    {"error": "Query parameter 'agg' must be 'sum' or 'avg'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if agg == "sum":
                result = queryset.aggregate(value=Sum("value"))
            else:  # avg
                result = queryset.aggregate(value=Avg("value"))

            serializer = serializers.AggregatedMetricSerializer(
                {
                    "key": key,
                    "service_id": service_id,
                    "aggregation": agg,
                    "value": result["value"] or 0,
                    "count": queryset.count(),
                }
            )
            return Response(serializer.data)

        # Handle group_by parameter
        group_by = request.query_params.get("group_by")
        if group_by == "organization":
            # Group by organization and sum values
            grouped = (
                queryset.values("organization__id", "organization__name")
                .annotate(value=Sum("value"))
                .order_by("organization__name")
            )
            results = [
                {
                    "organization": {
                        "id": str(item["organization__id"]),
                        "name": item["organization__name"],
                    },
                    "value": str(item["value"]),
                }
                for item in grouped
            ]
            return Response({"results": results, "grouped_by": "organization"})

        # Return list of metrics
        queryset = queryset.select_related("account", "organization").order_by(
            "organization__name", "account__email"
        )
        serializer = serializers.MetricSerializer(queryset, many=True)
        return Response({"results": serializer.data})
