"""
API endpoints for Metrics model.
"""

import uuid

from django.db.models import Avg, Sum

from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from core import models
from core.authentication import OperatorExternalManagementApiKeyAuthentication

from .. import permissions
from .. import serializers as core_serializers
from . import Pagination


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


def _parse_uuid_list(value):
    """Parse a comma-separated list of UUIDs, naming the one that is malformed."""
    parsed = []
    for raw in value.split(","):
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            parsed.append(uuid.UUID(candidate))
        except ValueError as exc:
            raise serializers.ValidationError(
                f"'{candidate}' is not a valid UUID."
            ) from exc
    return parsed


# account_type value selecting the metrics stored without an account
# (organization-level rows from the service's metrics endpoint).
NO_ACCOUNT_TYPE = "none"


class OperatorMetricsQuerySerializer(serializers.Serializer):
    """Validate query params for the operator metrics endpoint.

    Everything the view reads goes through here, so a malformed value comes back
    as a 400 naming the parameter instead of reaching the ORM.
    """

    key = serializers.CharField()
    service = serializers.IntegerField()
    organizations = serializers.CharField(required=False, allow_blank=True)
    accounts = serializers.CharField(required=False, allow_blank=True)
    # Required: a service can report the same key per account and for the whole
    # organization, and adding those up counts the same usage twice.
    account_type = serializers.CharField()
    agg = serializers.ChoiceField(
        choices=["sum", "avg"], required=False, allow_blank=True
    )
    group_by = serializers.ChoiceField(
        choices=["organization"], required=False, allow_blank=True
    )
    order_by = serializers.ChoiceField(
        choices=["organization", "value", "-value"], required=False, allow_blank=True
    )

    def validate_organizations(self, value):
        """Turn the comma-separated param into a list of UUIDs."""
        return _parse_uuid_list(value)

    def validate_accounts(self, value):
        """Turn the comma-separated param into a list of UUIDs."""
        return _parse_uuid_list(value)


class OperatorMetricKeysQuerySerializer(serializers.Serializer):
    """Validate query params for the operator metric keys endpoint."""

    service = serializers.IntegerField(required=False)


class OperatorMetricsViewSet(viewsets.ViewSet):
    """ViewSet for Metrics model nested under Operator.

    GET /api/v1.0/operators/<operator_id>/metrics/
        Return the list of metrics for the given operator based on filters.
        Supports filtering by key, service, organizations, accounts, account_type.
        Supports aggregation via agg=sum|avg query param.

    GET /api/v1.0/operators/<operator_id>/metrics/keys/
        Return the metric keys that have data for this operator, each with the
        account types it has data for.

    Required query params:
        - key: Metric key to filter on (single value)
        - service: Service ID to filter on (single value)
        - account_type: Account type (e.g. "user", "mailbox", "organization"), or
          "none" for the metrics stored without an account.

    Optional query params:
        - organizations: Comma-separated organization IDs. Defaults to all orgs the operator has access to.
        - accounts: Comma-separated account IDs. If omitted, returns all accounts of the type.
        - agg: Aggregation type (sum|avg). If provided, returns aggregated value.
        - group_by: Group results by 'organization'. Returns sum per organization.
        - page / page_size: Paginate the listed and grouped results.
    """

    # A list literal, not list(...): the class also defines a "list" method below,
    # and reading the builtin by that name here is a trap for the next reader.
    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
        *api_settings.DEFAULT_AUTHENTICATION_CLASSES,
    ]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAccessPermission,
    ]

    def _operator_metrics(self, operator_id):
        """Metrics of every organization the operator has a role in.

        The join cannot duplicate a metric: OperatorOrganizationRole is unique per
        (operator, organization). Filtering through it beats fetching the operator's
        organization IDs and passing them back as an IN clause, which costs a
        second query and grows with the operator (~300ms against 36k organizations,
        against ~2ms here).
        """
        return models.Metric.objects.filter(
            organization__operator_roles__operator_id=operator_id
        )

    @staticmethod
    def _paginated_response(paginator, results, **extra):
        """The standard paginated payload, plus endpoint-specific keys."""
        return Response(
            {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": results,
                **extra,
            }
        )

    def list(self, request, operator_id=None):
        """List metrics with filtering and optional aggregation."""
        query = OperatorMetricsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        try:
            service = models.Service.objects.get(id=params["service"])
        except models.Service.DoesNotExist:
            return Response(
                {"error": f"Service with id '{params['service']}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        queryset = self._operator_metrics(operator_id).filter(
            key=params["key"],
            service=service,
        )

        # Requested organizations are kept only where the operator has a role, so a
        # foreign ID cannot widen the scope. All of them being foreign is a mistake
        # worth reporting rather than answering with an empty chart.
        organizations = params.get("organizations")
        if organizations:
            if not models.Organization.objects.filter(
                operator_roles__operator_id=operator_id, id__in=organizations
            ).exists():
                return Response(
                    {"error": "No valid organizations found for the given IDs."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(organization_id__in=organizations)

        if params["account_type"] == NO_ACCOUNT_TYPE:
            queryset = queryset.filter(account__isnull=True)
        else:
            queryset = queryset.filter(account__type=params["account_type"])

        if params.get("accounts"):
            queryset = queryset.filter(account_id__in=params["accounts"])

        agg = params.get("agg")
        if agg:
            aggregation = Sum("value") if agg == "sum" else Avg("value")
            result = queryset.aggregate(value=aggregation)

            serializer = core_serializers.AggregatedMetricSerializer(
                {
                    "key": params["key"],
                    "service_id": service.id,
                    "aggregation": agg,
                    "value": result["value"] or 0,
                    "count": queryset.count(),
                }
            )
            return Response(serializer.data)

        paginator = Pagination()

        # Every ordering ends on a unique column. Sorting by value alone leaves
        # ties in an order Postgres is free to change between pages, which is how
        # a row shows up twice, or never, while paging.
        order_by = params.get("order_by") or "organization"

        if params.get("group_by") == "organization":
            # Organization.name is not unique: the DPNT dataset has 1454 names
            # shared by several communes, a dozen of them for "Sainte-Colombe".
            # Without the id, those rows tie and the database is free to order
            # them differently per page, which duplicates one and drops another.
            grouped_order = {
                "organization": ["organization__name", "organization__id"],
                "value": ["value", "organization__name", "organization__id"],
                "-value": ["-value", "organization__name", "organization__id"],
            }[order_by]
            grouped = (
                queryset.values("organization__id", "organization__name")
                .annotate(value=Sum("value"))
                .order_by(*grouped_order)
            )
            page = paginator.paginate_queryset(grouped, request, view=self)
            results = [
                {
                    "organization": {
                        "id": str(item["organization__id"]),
                        "name": item["organization__name"],
                    },
                    "value": str(item["value"]),
                }
                for item in page
            ]
            return self._paginated_response(
                paginator, results, grouped_by="organization"
            )

        # "id" breaks ties: accounts of the same organization can share an empty
        # email, and without it a row could show up on two pages or on none.
        row_order = {
            "organization": ["organization__name", "account__email", "id"],
            "value": ["value", "id"],
            "-value": ["-value", "id"],
        }[order_by]
        queryset = queryset.select_related("account", "organization").order_by(
            *row_order
        )
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = core_serializers.MetricSerializer(page, many=True)
        return self._paginated_response(paginator, serializer.data)

    def keys(self, request, operator_id=None):
        """List the metric keys that have data for this operator, each with the
        account types it has data for ("none" for rows without an account).

        The dashboard populates its key and account type filters from this
        rather than from hardcoded lists, so it only offers what resolves to a
        chart.
        """
        query = OperatorMetricKeysQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        queryset = self._operator_metrics(operator_id)

        service_id = query.validated_data.get("service")
        if service_id:
            queryset = queryset.filter(service_id=service_id)

        # order_by clears Metric's default ordering, which would otherwise add
        # "timestamp" to the selected columns and defeat the distinct().
        rows = queryset.values_list("key", "account__type").distinct().order_by()
        account_types = {}
        for key, account_type in rows:
            account_types.setdefault(key, set()).add(
                NO_ACCOUNT_TYPE if account_type is None else account_type
            )
        return Response(
            {
                "results": [
                    {"key": key, "account_types": sorted(types)}
                    for key, types in sorted(account_types.items())
                ]
            }
        )
