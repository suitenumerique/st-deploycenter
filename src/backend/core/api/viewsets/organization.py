"""
API endpoints for Organization model.
"""

import rest_framework as drf
from rest_framework import viewsets

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

    def get_queryset(self):
        return (
            models.Organization.objects.filter(operators__id=self.kwargs["operator_id"])
            .prefetch_related("service_subscriptions__service")
            .all()
        )


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
