"""
Entitlements API viewsets.
"""

from django.conf import settings
from django.db.models import BooleanField, Case, Exists, OuterRef, Q, Value, When

import rest_framework as drf
from drf_spectacular.utils import OpenApiResponse, extend_schema
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
from core.entitlements.resolvers.piggyback_access_entitlement_resolver import (
    PiggybackAccessEntitlementResolver,
)
from core.tasks.metrics import scrape_service_usage_metrics, store_service_metrics


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
    idp_id = serializers.CharField(required=False)

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


# pylint: disable=abstract-method
class EntitlementUsageMetricsPushSerializer(serializers.Serializer):
    """
    Optional POST body: usage metric items in the same format as the
    service's usage_metrics_endpoint results, passed through unchanged
    to store_service_metrics.
    """

    usage_metrics = serializers.ListField(child=serializers.DictField(), required=False)

    def validate_usage_metrics(self, value):
        """
        Only validate the shapes the view relies on; anything else stays as
        tolerant as the scrape path (bad rows are logged and skipped).
        """
        for index, item in enumerate(value):
            if item.get("account") is not None and not isinstance(
                item["account"], dict
            ):
                raise serializers.ValidationError(
                    f"Item {index}: 'account' must be an object."
                )
            if item.get("metrics") is not None and not isinstance(
                item["metrics"], dict
            ):
                raise serializers.ValidationError(
                    f"Item {index}: 'metrics' must be an object."
                )
        return value


def _refresh_usage_metrics(entitlement_context, entitlements_by_type, usage_metrics):
    """
    Store caller-pushed usage metrics and scrape the scopes they don't cover.
    The caller is the service itself, so pushed items are as trusted as its
    usage_metrics_endpoint.
    """
    service = entitlement_context["service"]
    account_type = entitlement_context["account_type"]

    # Always scrape incoming account metrics. (user, mailbox, etc.)
    scrape_account = True
    # Not all services supports organization account type.
    scrape_organization = False

    # Determine if we need to scrape organization metrics.
    # We scrape organization metrics only if we have at least one organization entitlement.
    for entitlements_of_type in entitlements_by_type.values():
        entitlements_by_priority = get_entitlements_by_priority(entitlements_of_type)
        if entitlements_by_priority.get("organization"):
            scrape_organization = True

    # Store the pushed metrics and skip the scrape for each account type
    # they cover.
    pushed_account_types = set()
    if usage_metrics:
        for item in usage_metrics:
            item_account_type = (item.get("account") or {}).get("type")
            if item_account_type:
                pushed_account_types.add(item_account_type)
        store_service_metrics(service, usage_metrics)

    # Scrape metrics.
    if scrape_account and account_type not in pushed_account_types:
        scrape_filters = {
            "account_type": account_type,
        }
        if entitlement_context["account_id"]:
            scrape_filters["account_id_value"] = entitlement_context["account_id"]
        if entitlement_context["account_email"]:
            scrape_filters["account_email"] = entitlement_context["account_email"]
        scrape_service_usage_metrics(service, scrape_filters)
    if scrape_organization and "organization" not in pushed_account_types:
        scrape_service_usage_metrics(
            service,
            {
                "account_type": "organization",
                "account_id_key": "siret",
                "account_id_value": entitlement_context["siret"],
            },
        )


def _get_piggyback_operator_data(access_resolver, entitlement_context):
    """Return source-subscription operator data when access piggybacks, else None."""
    if not isinstance(access_resolver, PiggybackAccessEntitlementResolver):
        return None
    source_subscription = access_resolver.get_source_subscription(entitlement_context)
    if not source_subscription or not source_subscription.is_active:
        return None
    return EntitlementOperatorSerializer(source_subscription.operator).data


def _find_potential_operators(organization, service):
    """Find potential operators for an organization+service pair.

    Returns a list of dicts with serialized operator data, signupUrl, and match flags.
    Uses a single query combining two strategies:
    1. Operator has an OperatorOrganizationRole with this organization
    2. Operator's config.departements contains the organization's departement_code_insee
       (not applicable for regions)
    """
    has_org_role = Exists(
        models.OperatorOrganizationRole.objects.filter(
            operator=OuterRef("operator"),
            organization=organization,
        )
    )

    dept_code = organization.departement_code_insee
    if organization.type != "region" and dept_code:
        has_dept_match = Case(
            When(
                operator__config__departements__contains=[dept_code],
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        )
    else:
        has_dept_match = Value(False, output_field=BooleanField())

    oscs = (
        models.OperatorServiceConfig.objects.filter(
            service=service, operator__is_active=True
        )
        .select_related("operator")
        .annotate(
            has_org_role=has_org_role,
            has_dept_match=has_dept_match,
        )
        .filter(Q(has_org_role=True) | Q(has_dept_match=True))
        .order_by("-has_org_role", "-display_priority", "operator__name")
    )

    result = []
    base_url = settings.SUITE_TERRITORIALE_BASE_URL.rstrip("/")
    for osc in oscs:
        can_activate, _reason = service.can_activate(organization, osc.operator)
        if not can_activate:
            continue
        op_data = EntitlementOperatorSerializer(osc.operator).data
        op_data["signupUrl"] = (
            f"{base_url}/bienvenue/"
            f"{organization.siret}/contact"
            f"?operator={osc.operator.id}&services={service.id}"
        )
        result.append(op_data)

    return result


class EntitlementView(APIView):
    """
    Entitlement view.
    """

    permission_classes = [permissions.ServiceAuthenticationPermission]

    def get(self, request):
        """
        Get entitlements.
        """
        return self._resolve_entitlements(request)

    @extend_schema(
        request=EntitlementUsageMetricsPushSerializer,
        responses={200: OpenApiResponse(description="Same response as GET.")},
    )
    def post(self, request):
        """
        Get entitlements, exactly like GET (same query params, same response).

        Additionally accepts an optional JSON body:
        {"usage_metrics": [<items in the usage_metrics_endpoint format>]}
        Pushed items are stored as if they had been scraped, and suppress the
        HTTP scrape back to the service for each account type they cover
        (the query param account_type and/or "organization"). Scopes not
        covered by the body are still scraped as usual.
        """
        body_serializer = EntitlementUsageMetricsPushSerializer(data=request.data)
        body_serializer.is_valid(raise_exception=True)
        # An empty list behaves exactly like an absent key (full scraping).
        usage_metrics = body_serializer.validated_data.get("usage_metrics") or None
        return self._resolve_entitlements(request, usage_metrics=usage_metrics)

    def _resolve_entitlements(self, request, usage_metrics=None):
        """
        Resolve entitlements for the given request query params. When
        usage_metrics items are provided, they replace the corresponding
        usage-metrics scrapes.
        """

        serializer = EntitlementViewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        siret = serializer.validated_data["siret"]

        organization = models.Organization.objects.filter(siret=siret).first()

        # Reuse the service already fetched by ServiceAuthenticationPermission.
        service = getattr(request, "service", None)
        if not service:
            raise drf.exceptions.NotFound(
                "Service not found. Make sure the service exists."
            )

        service_subscription = None
        if organization:
            # We should always have one or none service subscription for an organization-service pair.
            service_subscription = (
                models.ServiceSubscription.objects.select_related("operator")
                .filter(organization=organization, service=service)
                .first()
            )

        # Response building.
        account_type = serializer.validated_data["account_type"]
        account_id = serializer.validated_data.get("account_id")
        account_email = serializer.validated_data.get("account_email")

        operator_data = None
        potential_operators_data = None
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
        access_resolver = get_access_entitlement_resolver(service)
        entitlements_data = {**access_resolver.resolve(entitlement_context)}
        metrics_data = {}

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

            _refresh_usage_metrics(
                entitlement_context, entitlements_by_type, usage_metrics
            )

            # Resolve entitlements.
            for entitlement_type, entitlements_of_type in entitlements_by_type.items():
                resolver = get_entitlement_resolver(entitlement_type)
                entitlement_data = resolver.resolve(
                    {**entitlement_context, "entitlements": entitlements_of_type}
                )
                entitlements_data = {**entitlements_data, **entitlement_data}
                metrics_data = {**metrics_data, **resolver.metrics_data}

            # Resolve admin entitlement.
            entitlements_data = {
                **entitlements_data,
                **get_admin_entitlement_resolver(service).resolve(entitlement_context),
            }
        elif organization:
            # For piggyback services (e.g. transfers on top of drive), there is
            # no local subscription — surface the source subscription's operator
            # so the response is consistent with can_access.
            operator_data = _get_piggyback_operator_data(
                access_resolver, entitlement_context
            )
            if operator_data is None:
                potential_operators_data = _find_potential_operators(
                    organization, service
                )

        organization_data = None
        if organization:
            oidc_valid = None
            idp_id = serializer.validated_data.get("idp_id")
            if idp_id and organization.type in (
                "commune",
                "region",
                "departement",
                "epci",
            ):
                oidc_valid = models.ServiceSubscription.objects.filter(
                    organization=organization,
                    service__type="proconnect",
                    is_active=True,
                    service__config__idp_id=idp_id,
                ).exists()

            organization_data = {
                "id": str(organization.id),
                "type": organization.type,
                "name": organization.name,
                "oidc_valid": oidc_valid,
            }

        response_data = {
            "organization": organization_data,
            "operator": operator_data,
            "entitlements": entitlements_data,
            "metrics": metrics_data,
        }
        if potential_operators_data is not None:
            response_data["potentialOperators"] = potential_operators_data
        if metrics_data:
            response_data["metrics"] = metrics_data
        return Response(response_data)
