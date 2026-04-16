"""
API endpoints for Organization model.
"""

import logging

from django.db.models import Prefetch

from rest_framework import filters, viewsets
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.authentication import OperatorExternalManagementApiKeyAuthentication

from .. import permissions, serializers

logger = logging.getLogger(__name__)


class OperatorOrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Organization model nested in Operator model.

    GET /api/v1.0/operators/<operator_id>/organizations/
        Return the list of organizations for the given operator based on the user's permissions.
        Supports both user authentication and external API key authentication.
    """

    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
    ] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAccessPermission,
    ]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "departement_code_insee", "epci_libelle"]

    def get_queryset(self):
        operator_id = self.kwargs["operator_id"]
        subscriptions_queryset = models.ServiceSubscription.objects.filter(
            operator=operator_id
        ).select_related("service", "operator")
        operator_roles_queryset = models.OperatorOrganizationRole.objects.filter(
            operator_id=operator_id
        )

        queryset = (
            models.Organization.objects.filter(operators__id=operator_id)
            .prefetch_related(
                Prefetch("service_subscriptions", queryset=subscriptions_queryset),
                Prefetch(
                    "operator_roles",
                    queryset=operator_roles_queryset,
                    to_attr="prefetched_operator_roles",
                ),
            )
            .all()
        )

        # Filter by type if provided
        if self.request.query_params.get("type"):
            type_filter = self.request.query_params.get("type")
            queryset = queryset.filter(type=type_filter)

        # Filter by service if provided (organizations with active subscription to this service)
        if self.request.query_params.get("service"):
            service_filter = self.request.query_params.get("service")
            queryset = queryset.filter(
                service_subscriptions__service_id=service_filter,
                service_subscriptions__operator_id=self.kwargs["operator_id"],
                service_subscriptions__is_active=True,
            )

        if self.request.query_params.get("search"):
            search_query = self.request.query_params.get("search")

            # Use ILIKE for partial word matching with accent-insensitive search
            # Also search by SIRET and SIREN (exact match for both)
            queryset = queryset.extra(
                where=[
                    """
                    unaccent_immutable(name) ILIKE unaccent_immutable(%s) OR
                    unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) OR
                    unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s) OR
                    siret = %s OR
                    code_postal = %s OR
                    siren = %s
                    """
                ],
                params=[
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                    search_query,
                    search_query,
                    search_query,
                ],
            )

            # Order by match priority: SIRET first, then SIREN (both exact matches),
            # then name, then departement_code_insee, then epci_libelle
            queryset = queryset.extra(
                select={
                    "match_priority": """
                        CASE 
                            WHEN siret = %s THEN 1
                            WHEN siren = %s THEN 2
                            WHEN code_postal = %s THEN 3
                            WHEN unaccent_immutable(name) ILIKE unaccent_immutable(%s) THEN 4
                            WHEN unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) THEN 5
                            WHEN unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s) THEN 6
                            ELSE 6
                        END
                    """
                },
                select_params=[
                    search_query,
                    search_query,
                    search_query,
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                ],
                order_by=["match_priority", "name"],
            )
        return queryset

    @action(detail=True, methods=["patch"], url_path="operator-role")
    def operator_role(self, request, *args, **kwargs):
        """Update the OperatorOrganizationRole settings for this org+operator."""
        organization = self.get_object()
        operator_id = self.kwargs["operator_id"]

        role = models.OperatorOrganizationRole.objects.filter(
            operator_id=operator_id, organization=organization
        ).first()
        if not role:
            logger.warning(
                "operator_role: no role found for org=%s operator=%s",
                organization.pk,
                operator_id,
            )
            return Response(
                {"detail": "No operator role found for this organization."},
                status=404,
            )

        if "operator_admins_have_admin_role" in request.data:
            value = request.data["operator_admins_have_admin_role"]
            if not isinstance(value, bool):
                raise drf_serializers.ValidationError(
                    {"operator_admins_have_admin_role": "Must be a boolean."}
                )
            previous = role.operator_admins_have_admin_role
            role.operator_admins_have_admin_role = value
            role.save(update_fields=["operator_admins_have_admin_role", "updated_at"])
            logger.info(
                "operator_role: toggled operator_admins_have_admin_role "
                "%s→%s for org=%s operator=%s",
                previous,
                value,
                organization.pk,
                operator_id,
            )

        return Response(
            {"operator_admins_have_admin_role": role.operator_admins_have_admin_role}
        )
