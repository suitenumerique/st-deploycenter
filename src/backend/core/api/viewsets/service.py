"""
API endpoints for Service model.
"""
# pylint: disable=line-too-long

import logging

from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.authentication import (
    OperatorExternalManagementApiKeyAuthentication,
    ServiceExternalManagementApiKeyAuthentication,
)
from core.signals import request_user_context, suppress_proconnect_sync

from .. import permissions, serializers

logger = logging.getLogger(__name__)


class ServiceLogoViewSet(viewsets.ReadOnlyModelViewSet):
    """Public ViewSet for serving service logos as SVG files."""

    queryset = models.Service.objects.filter(is_active=True, logo_svg__isnull=False)
    permission_classes = [AllowAny]
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        """
        Serve the service logo as an SVG file with proper headers.
        """
        service = self.get_object()

        if not service.logo_svg:
            return Response(
                {"detail": "Logo not found for this service"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Create response with SVG content
        response = HttpResponse(
            service.logo_svg, content_type="image/svg+xml; charset=utf-8"
        )

        # Set appropriate headers for SVG files
        response["Content-Disposition"] = 'inline; filename="logo.svg"'
        response["Cache-Control"] = "public, max-age=3600"  # Cache for 1 hour
        response["Access-Control-Allow-Origin"] = "*"  # Allow CORS for public access

        return response


class OrganizationServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for OrganizationService model.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/
        Return the list of services including the subscription for the given organization
        based on the user's permissions.

    Supports both user authentication and external API key authentication.
    """

    queryset = models.Service.objects.all()
    serializer_class = serializers.OrganizationServiceSerializer
    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
        ServiceExternalManagementApiKeyAuthentication,
    ] + [*api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission
        | permissions.ServiceExternalManagementPermission,
    ]

    def get_queryset(self):
        organization_id = self.kwargs["organization_id"]
        operator_id = self.kwargs["operator_id"]

        return (
            models.Service.objects.filter(
                Q(
                    operatorserviceconfig__operator_id=operator_id,
                )
                # Also include services that have subscriptions for this org (any operator)
                | Q(subscriptions__organization_id=organization_id)
            )
            .prefetch_related(
                Prefetch(
                    "subscriptions",
                    queryset=models.ServiceSubscription.objects.filter(
                        organization_id=organization_id, operator_id=operator_id
                    ).select_related("operator"),
                ),
                Prefetch(
                    "operatorserviceconfig_set",
                    queryset=models.OperatorServiceConfig.objects.filter(
                        operator_id=operator_id,
                    ),
                ),
                # Prefetch other operator subscription for read-only visibility
                Prefetch(
                    "subscriptions",
                    queryset=models.ServiceSubscription.objects.filter(
                        organization_id=organization_id,
                    )
                    .exclude(operator_id=operator_id)
                    .select_related("operator"),
                    to_attr="other_operator_subscription_prefetched",
                ),
            )
            .prefetch_related("subscriptions__entitlements")
            .distinct()
            .order_by("id")
        )

    def get_serializer_context(self):
        """Add operator_id and organization to serializer context."""
        context = super().get_serializer_context()
        context["operator_id"] = self.kwargs["operator_id"]
        try:
            organization = models.Organization.objects.get(
                id=self.kwargs["organization_id"]
            )
        except models.Organization.DoesNotExist as err:
            raise NotFound("Organization not found.") from err
        context["organization"] = organization
        return context


class OrganizationServiceSubscriptionViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganizationServiceSubscription model.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Get the subscription for the given organization and service.

    PATCH /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Create or update the subscription for the given organization and service.
        Creates the subscription if it doesn't exist (upsert behavior).

    DELETE /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/
        Delete the subscription for the given organization and service.

    Supports both user authentication and external API key authentication.
    """

    queryset = models.ServiceSubscription.objects.all()
    serializer_class = serializers.ServiceSubscriptionSerializer
    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
        ServiceExternalManagementApiKeyAuthentication,
    ] + [*api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission
        | permissions.ServiceExternalManagementPermission,
    ]

    def get_queryset(self):
        return models.ServiceSubscription.objects.filter(
            organization=self.kwargs["organization_id"],
            service=self.kwargs["service_id"],
            operator=self.kwargs["operator_id"],
        )

    def get_object(self):
        """
        Get the subscription for the operator-organization-service triple.
        Since there can only be one subscription per operator-organization-service triple,
        we return it directly without requiring a pk in the URL.
        """
        queryset = self.get_queryset()
        try:
            return queryset.get()
        except models.ServiceSubscription.DoesNotExist as err:
            raise NotFound(
                "Subscription not found for this operator-organization-service triple."
            ) from err

    def list(self, request, *args, **kwargs):
        """
        List method is not implemented for this viewset.
        Use retrieve() to get the subscription for the operator-organization-service triple.
        """
        return Response(
            {"detail": "Method not allowed. Use GET to retrieve the subscription."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def retrieve(self, request, *args, **kwargs):
        """
        Return the subscription for the operator-organization-service triple.
        """
        subscription = self.get_object()
        serializer = self.get_serializer(subscription)
        return Response(serializer.data)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update or create the subscription for the operator-organization-service triple.
        Creates the subscription if it doesn't exist (upsert behavior).
        """
        # Suppress the per-save ProConnect push so we can fire it exactly ONCE, as
        # the LAST operation before commit (after entitlement writes). Otherwise the
        # push happens at .save()/.create() time and a later entitlement-write
        # failure would roll back the DB while the provider already has the new
        # domains — drift. Still inside @transaction.atomic, so a push failure rolls
        # back the whole subscription + entitlement change and returns 502.
        with request_user_context(request.user), suppress_proconnect_sync():
            # Locked, so that a transfer to another operator cannot be overwritten
            # by this request's stale copy of the row.
            subscription = self._locked_subscription()

            organization = models.Organization.objects.get(
                id=self.kwargs["organization_id"]
            )
            service = models.Service.objects.filter(
                id=self.kwargs["service_id"]
            ).first()
            if service is None:
                raise NotFound("Service not found.")
            operator = models.Operator.objects.get(id=self.kwargs["operator_id"])

            if (
                subscription is None
                and models.ServiceSubscription.objects.filter(
                    organization=organization, service=service
                ).exists()
            ):
                raise PermissionDenied(
                    "This service is managed by another operator for this organization."
                )

            is_configured = models.OperatorServiceConfig.objects.filter(
                operator=operator, service=service
            ).exists()
            if subscription is None and not is_configured:
                raise PermissionDenied(
                    "This service is not available for this operator."
                )

            # Validate request data
            serializer = self.get_serializer(
                subscription, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)

            # An existing subscription to a service no longer configured for the
            # operator may still be deactivated, but not kept or made active.
            is_active = serializer.validated_data.get(
                "is_active", subscription.is_active if subscription else False
            )
            if is_active and not is_configured:
                raise PermissionDenied(
                    "This service is not available for this operator."
                )

            if subscription:
                created = False
                serializer.save()  # runs apply_entitlement_configs (push suppressed)
            else:
                created = True
                is_active = serializer.validated_data.get("is_active", False)
                metadata = serializer.validated_data.get("metadata", {})
                subscription = models.ServiceSubscription.objects.create(
                    organization=organization,
                    service=service,
                    operator=operator,
                    is_active=is_active,
                    metadata=metadata,
                )
                serializer.instance = subscription
                serializer.apply_entitlement_configs(subscription)

        # Push last. The pre_save signal recorded what the subscription routed
        # before, so only the domains this request added or removed are pushed, and
        # an unrelated edit pushes nothing.
        if service.type == "proconnect":
            from core.services.proconnect import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
                push_subscription_domains,
            )

            push_subscription_domains(
                subscription, getattr(subscription, "_proconnect_before", None)
            )

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(self.get_serializer(subscription).data, status=status_code)

    @extend_schema(request=None, responses=serializers.ServiceSubscriptionSerializer)
    @transaction.atomic
    def change_operator(self, request, *args, **kwargs):
        """
        Reassign the subscription of another operator to the operator in the URL.

        Superusers only: operators never act on a subscription they do not own.
        The state, metadata and entitlements are left as they are, but the
        subscription is saved (and validated) as one of the new operator: an active
        one that operator may not activate (population limit) is refused with a 400,
        and the new operator's webhooks and service config now apply to it. The
        previous operator gets no event.

        The move is recorded in the organization's admin history.
        """
        # External API keys authenticate without a user.
        if request.user is None or not request.user.is_superuser:
            raise PermissionDenied(
                "Only superusers can change the operator of a subscription."
            )

        operator = get_object_or_404(models.Operator, id=self.kwargs["operator_id"])
        # Only this row is locked: the joins of select_related and of the model's
        # ordering would lock the organization, service and operator rows too, for
        # as long as the webhooks take.
        subscription = (
            models.ServiceSubscription.objects.select_for_update(of=("self",))
            .select_related("service", "operator", "organization")
            .filter(
                organization=self.kwargs["organization_id"],
                service=self.kwargs["service_id"],
            )
            .first()
        )
        if subscription is None:
            raise NotFound("Subscription not found.")
        previous_operator = subscription.operator
        if previous_operator.pk == operator.pk:
            raise ValidationError("This subscription already belongs to this operator.")

        config = models.OperatorServiceConfig.objects.filter(
            operator=operator, service=subscription.service
        ).first()
        if config is None:
            raise PermissionDenied("This service is not available for this operator.")
        if config.externally_managed:
            raise PermissionDenied(
                "This service is managed externally for this operator."
            )

        with request_user_context(request.user):
            subscription.operator = operator
            subscription.save()

        self._log_operator_change(
            request.user, subscription, previous_operator, operator
        )
        return Response(self.get_serializer(subscription).data)

    @staticmethod
    def _log_operator_change(user, subscription, previous_operator, operator):
        """Record who moved a subscription, and from which operator."""
        change_message = (
            f"Subscription to {subscription.service.name} moved from operator "
            f"{previous_operator.name} ({previous_operator.pk}) to "
            f"{operator.name} ({operator.pk})"
        )
        logger.info(
            "%s for org=%s by user=%s",
            change_message,
            subscription.organization_id,
            user.pk,
        )
        LogEntry.objects.log_actions(
            user.pk,
            [subscription.organization],
            CHANGE,
            change_message=change_message,
            single_object=True,
        )

    def _locked_subscription(self):
        """This operator's subscription for the organization and service, row-locked.

        ``None`` when there is none. Only the subscription row is locked, not the
        rows the model's ordering joins in.
        """
        return self.get_queryset().select_for_update(of=("self",)).first()

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """
        Delete the subscription for the operator-organization-service triple.

        Atomic so that a failed ProConnect domains push (fired on delete) rolls back
        the deletion instead of drifting from the provider.
        """
        with request_user_context(request.user):
            # Locked, so that a transfer in flight cannot lose its row to this
            # request's stale copy of it.
            subscription = self._locked_subscription()
            if subscription is None:
                raise NotFound(
                    "Subscription not found for this operator-organization-service triple."
                )
            subscription.delete()
            return Response({}, status=status.HTTP_204_NO_CONTENT)


class OrganizationServiceSubscriptionEntitlementViewSet(
    mixins.ListModelMixin, viewsets.GenericViewSet
):
    """ViewSet for OrganizationServiceSubscriptionEntitlement model.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/services/<service_id>/subscription/entitlements/
        Get the entitlements for the given organization and service.
        Supports filtering.
    """

    queryset = models.Entitlement.objects.all()
    serializer_class = serializers.EntitlementSerializer
    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
        ServiceExternalManagementApiKeyAuthentication,
    ] + [*api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission
        | permissions.ServiceExternalManagementPermission,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["type", "account_type", "account__id", "account__external_id"]

    def get_queryset(self):
        queryset = models.Entitlement.objects.filter(
            service_subscription__organization=self.kwargs["organization_id"],
            service_subscription__service=self.kwargs["service_id"],
            service_subscription__operator=self.kwargs["operator_id"],
        )
        return queryset


class SubscriptionEntitlementViewSet(
    viewsets.GenericViewSet, mixins.RetrieveModelMixin, mixins.UpdateModelMixin
):
    """ViewSet for SubscriptionEntitlement model.

    GET /api/v1.0/entitlements/<entitlement_id>/
        Get the entitlement for the given entitlement id.

    PATCH /api/v1.0/entitlements/<entitlement_id>/
        Partially update the entitlement for the given entitlement id.
    """

    queryset = models.Entitlement.objects.all()
    serializer_class = serializers.EntitlementSerializer
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.SubscriptionEntitlementAccessPermission,
    ]
