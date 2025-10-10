"""
API endpoints for Organization model.
"""

import rest_framework as drf
from rest_framework import filters, viewsets

from core import models

from .. import permissions, serializers


class OperatorOrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Organization model nested in Operator model.

    GET /api/v1.0/operators/<operator_id>/organizations/
        Return the list of organizations for the given operator based on the user's permissions.
    """

    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        permissions.OperatorAccessPermission,
    ]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "departement_code_insee", "epci_libelle"]

    def get_queryset(self):
        queryset = (
            models.Organization.objects.filter(operators__id=self.kwargs["operator_id"])
            .prefetch_related("service_subscriptions__service")
            .all()
        )

        if self.request.query_params.get("search"):
            search_query = self.request.query_params.get("search")

            # Use ILIKE for partial word matching with accent-insensitive search
            queryset = queryset.extra(
                where=[
                    """
                    unaccent_immutable(name) ILIKE unaccent_immutable(%s) OR
                    unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) OR
                    unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s)
                    """
                ],
                params=[f"%{search_query}%"] * 3,
            )

            # Order by match priority: name first, then departement_code_insee, then epci_libelle
            queryset = queryset.extra(
                select={
                    "match_priority": """
                        CASE 
                            WHEN unaccent_immutable(name) ILIKE unaccent_immutable(%s) THEN 1
                            WHEN unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) THEN 2
                            WHEN unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s) THEN 3
                            ELSE 4
                        END
                    """
                },
                select_params=[f"%{search_query}%"] * 3,
                order_by=["match_priority", "name"],
            )
        return queryset


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Organization model.

    GET /api/v1.0/organizations/<organization_id>
        Return the organization with the given id based on the user's permissions.
    """

    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        permissions.OrganizationAccessPermission,
    ]

    def get_queryset(self):
        return models.Organization.objects.all()

    def list(self, request, *args, **kwargs):
        raise drf.exceptions.NotFound
