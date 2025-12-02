"""
API endpoints for Organization model.
"""

from django.db.models import Prefetch

from rest_framework import filters, viewsets
from rest_framework.settings import api_settings

from core import models
from core.authentication import ExternalManagementApiKeyAuthentication

from .. import permissions, serializers


class OperatorOrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Organization model nested in Operator model.

    GET /api/v1.0/operators/<operator_id>/organizations/
        Return the list of organizations for the given operator based on the user's permissions.
        Supports both user authentication and external API key authentication.
    """

    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    authentication_classes = [
        ExternalManagementApiKeyAuthentication,
    ] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAccessPermission,
    ]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "departement_code_insee", "epci_libelle"]

    def get_queryset(self):
        subscriptions_queryset = models.ServiceSubscription.objects.filter(
            operator=self.kwargs["operator_id"]
        )

        queryset = (
            models.Organization.objects.filter(operators__id=self.kwargs["operator_id"])
            .prefetch_related(
                Prefetch("service_subscriptions", queryset=subscriptions_queryset)
            )
            .all()
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
                    siren = %s
                    """
                ],
                params=[
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
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
                            WHEN unaccent_immutable(name) ILIKE unaccent_immutable(%s) THEN 3
                            WHEN unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) THEN 4
                            WHEN unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s) THEN 5
                            ELSE 6
                        END
                    """
                },
                select_params=[
                    search_query,
                    search_query,
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                ],
                order_by=["match_priority", "name"],
            )
        return queryset
