"""
API endpoints for a service to manage its own subscriptions, authenticated with
its subscriptions API key (see docs/service_subscriptions_api.md).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.response import Response

from core import models
from core.api import permissions
from core.api.filters import ServiceKeySubscriptionFilter
from core.api.serializers import ServiceSubscriptionSerializer
from core.authentication import ServiceSubscriptionsApiKeyAuthentication
from core.services import bal as bal_service

# Metadata keys a service can read and write with its subscriptions API key, by
# service type. Any other key is refused.
SERVICE_KEY_METADATA_KEYS = {
    bal_service.SERVICE_TYPE: {bal_service.EPCI_DELEGATION_KEY},
}


def get_service_key_metadata_keys(service):
    """Metadata keys the subscriptions API key of this service can use."""
    return SERVICE_KEY_METADATA_KEYS.get(service.type, set())


def get_eligible_operators(service, organization=None):
    """Active operators configured for the service. With an organization, only
    the ones managing it (OperatorOrganizationRole)."""
    operators = models.Operator.objects.filter(is_active=True, services=service)
    if organization is not None:
        operators = operators.filter(organization_roles__organization=organization)
    return operators.distinct().order_by("name", "id")


class RejectUnknownFieldsMixin:
    """Refuse fields the serializer doesn't declare instead of ignoring them."""

    def validate(self, attrs):
        """Reject undeclared fields."""
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {field: ["Unknown field."] for field in unknown}
            )
        return attrs


class ServiceKeyMetadataMixin:
    """Optional metadata field, limited to get_service_key_metadata_keys().

    The serializer context must hold the "service".
    """

    def validate_metadata(self, value):
        """Refuse the keys the service cannot write."""
        allowed = get_service_key_metadata_keys(self.context["service"])
        refused = sorted(set(value) - allowed)
        if refused:
            raise serializers.ValidationError(
                f"Not writable with a subscriptions API key: {', '.join(refused)}."
            )
        return value


class ServiceKeyOperatorSerializer(serializers.ModelSerializer):
    """Operator, as exposed to a service."""

    class Meta:
        model = models.Operator
        fields = ["id", "name", "url"]
        read_only_fields = fields


class ServiceKeyOrganizationSerializer(serializers.ModelSerializer):
    """Organization, as exposed to a service."""

    class Meta:
        model = models.Organization
        fields = ["id", "siret", "name", "type"]
        read_only_fields = fields


class ServiceKeySubscriptionSerializer(serializers.ModelSerializer):
    """Subscription, as exposed to a service."""

    organization = ServiceKeyOrganizationSerializer(read_only=True)
    operator = ServiceKeyOperatorSerializer(read_only=True)
    metadata = serializers.SerializerMethodField()

    class Meta:
        model = models.ServiceSubscription
        fields = [
            "id",
            "organization",
            "operator",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_metadata(self, obj) -> dict:
        """Only the keys the service can write."""
        allowed = get_service_key_metadata_keys(obj.service)
        return {k: v for k, v in (obj.metadata or {}).items() if k in allowed}


# pylint: disable=abstract-method
class ServiceKeySubscriptionCreateSerializer(
    RejectUnknownFieldsMixin, ServiceKeyMetadataMixin, serializers.Serializer
):
    """POST body. Resolves the organization and checks the operator."""

    siret = serializers.CharField(max_length=14)
    operator_id = serializers.UUIDField()
    is_active = serializers.BooleanField()
    metadata = serializers.DictField(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        organization = models.Organization.objects.filter(siret=attrs["siret"]).first()
        if organization is None:
            raise serializers.ValidationError(
                {"siret": ["No organization with this SIRET."]}
            )
        operator = (
            get_eligible_operators(self.context["service"], organization)
            .filter(id=attrs["operator_id"])
            .first()
        )
        if operator is None:
            raise serializers.ValidationError(
                {
                    "operator_id": [
                        "This operator cannot manage this organization for this service."
                    ]
                }
            )
        return {
            "organization": organization,
            "operator": operator,
            "is_active": attrs["is_active"],
            "metadata": attrs.get("metadata", {}),
        }


# pylint: disable=abstract-method
class ServiceKeySubscriptionUpdateSerializer(
    RejectUnknownFieldsMixin, ServiceKeyMetadataMixin, serializers.Serializer
):
    """PATCH body: is_active, operator_id and/or metadata."""

    is_active = serializers.BooleanField(required=False)
    operator_id = serializers.UUIDField(required=False)
    metadata = serializers.DictField(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("metadata") == {}:
            del attrs["metadata"]
        if not attrs:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "Provide is_active, operator_id and/or metadata."
                    ]
                }
            )
        if "operator_id" in attrs:
            subscription = self.context["subscription"]
            operator = (
                get_eligible_operators(subscription.service, subscription.organization)
                .filter(id=attrs.pop("operator_id"))
                .first()
            )
            if operator is None:
                raise serializers.ValidationError(
                    {
                        "operator_id": [
                            "This operator cannot manage this organization for this service."
                        ]
                    }
                )
            attrs["operator"] = operator
        return attrs


class ServiceKeyMixin:
    """Authentication and permission shared by the endpoints of this module."""

    authentication_classes = [ServiceSubscriptionsApiKeyAuthentication]
    permission_classes = [permissions.ServiceSubscriptionsApiKeyPermission]

    def get_service(self):
        """The service of the API key. The permission ensured it is the one in the URL."""
        return self.request.auth.service


class ServiceSubscriptionsViewSet(
    ServiceKeyMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Subscriptions of a service, managed by that service.

    GET    /api/v1.0/services/<service_id>/subscriptions/
    POST   /api/v1.0/services/<service_id>/subscriptions/
    GET    /api/v1.0/services/<service_id>/subscriptions/<id>/
    PATCH  /api/v1.0/services/<service_id>/subscriptions/<id>/
    DELETE /api/v1.0/services/<service_id>/subscriptions/<id>/
    """

    serializer_class = ServiceKeySubscriptionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = ServiceKeySubscriptionFilter

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return models.ServiceSubscription.objects.none()
        return (
            models.ServiceSubscription.objects.filter(service=self.get_service())
            .select_related("organization", "operator")
            .order_by("organization__name", "id")
        )

    @staticmethod
    def _is_subscribed(organization, service):
        return models.ServiceSubscription.objects.filter(
            organization=organization, service=service
        ).exists()

    @extend_schema(
        request=ServiceKeySubscriptionCreateSerializer,
        responses={
            201: ServiceKeySubscriptionSerializer,
            409: OpenApiResponse(description="Organization already subscribed."),
        },
    )
    def create(self, request, *args, **kwargs):
        """Create a subscription. 409 if the organization already has one."""
        service = self.get_service()
        body = ServiceKeySubscriptionCreateSerializer(
            data=request.data, context={"service": service}
        )
        body.is_valid(raise_exception=True)
        organization = body.validated_data["organization"]
        conflict = Response(
            {"detail": "This organization is already subscribed to this service."},
            status=status.HTTP_409_CONFLICT,
        )

        try:
            with transaction.atomic():
                if self._is_subscribed(organization, service):
                    return conflict

                # Same business validation as the operator API (service-specific
                # metadata, activation rules).
                data = {"is_active": body.validated_data["is_active"]}
                if body.validated_data["metadata"]:
                    data["metadata"] = body.validated_data["metadata"]
                write = ServiceSubscriptionSerializer(
                    data=data,
                    context={
                        "request": request,
                        "organization": organization,
                        "service": service,
                    },
                )
                write.is_valid(raise_exception=True)
                subscription = models.ServiceSubscription.objects.create(
                    organization=organization,
                    service=service,
                    operator=body.validated_data["operator"],
                    is_active=body.validated_data["is_active"],
                    metadata=write.validated_data.get("metadata", {}),
                )
        except (IntegrityError, DjangoValidationError):
            # A concurrent request subscribed the organization after the check
            # above: the model's unique check or the database refused this one.
            if self._is_subscribed(organization, service):
                return conflict
            raise

        return Response(
            self.get_serializer(subscription).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        request=ServiceKeySubscriptionUpdateSerializer,
        responses={200: ServiceKeySubscriptionSerializer},
    )
    def partial_update(self, request, *args, **kwargs):
        """Change is_active, the operator and/or the allowed metadata keys."""
        with transaction.atomic():
            subscription = self.get_object()
            body = ServiceKeySubscriptionUpdateSerializer(
                data=request.data,
                context={"subscription": subscription, "service": subscription.service},
            )
            body.is_valid(raise_exception=True)

            # Saved by write.save() below. The model validation on save then checks
            # the activation rules with the new operator's config.
            if "operator" in body.validated_data:
                subscription.operator = body.validated_data["operator"]
            data = {}
            if "is_active" in body.validated_data:
                data["is_active"] = body.validated_data["is_active"]
            if "metadata" in body.validated_data:
                # Merged here: the shared serializer replaces the whole metadata
                # unless the service type's validator merges it itself.
                data["metadata"] = {
                    **(subscription.metadata or {}),
                    **body.validated_data["metadata"],
                }
            write = ServiceSubscriptionSerializer(
                subscription,
                data=data,
                partial=True,
                context={"request": request},
            )
            write.is_valid(raise_exception=True)
            write.save()

        return Response(self.get_serializer(subscription).data)

    def destroy(self, request, *args, **kwargs):
        """Delete a subscription."""
        with transaction.atomic():
            self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceOperatorsView(ServiceKeyMixin, generics.ListAPIView):
    """Operators a service can subscribe organizations with.

    GET /api/v1.0/services/<service_id>/operators/[?siret=<siret>]

    With siret, only the operators managing that organization: the valid
    operator_id values to create its subscription.
    """

    serializer_class = ServiceKeyOperatorSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "siret",
                str,
                description="Only the operators managing this organization.",
            )
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return models.Operator.objects.none()
        service = self.get_service()
        if "siret" not in self.request.query_params:
            return get_eligible_operators(service)

        siret = self.request.query_params["siret"]
        organization = (
            models.Organization.objects.filter(siret=siret).first() if siret else None
        )
        if organization is None:
            return models.Operator.objects.none()
        return get_eligible_operators(service, organization)
