"""
API endpoints for Operator model.
"""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core import models

from .. import permissions, serializers
from . import Pagination


class OperatorViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Operator model.

    GET /api/v1.0/operators/
        Return the list of operators based on the user's permissions.

    GET /api/v1.0/operators/<operator_id>
        Return the operator with the given id based on the user's permissions.

    GET /api/v1.0/operators/<operator_id>/services/
        Return the list of services configured for this operator.
    """

    queryset = models.Operator.objects.all()
    serializer_class = serializers.OperatorSerializer
    permission_classes = [permissions.IsAuthenticatedWithAnyMethod]
    pagination_class = Pagination

    def get_queryset(self):
        """
        Return only operators that the logged-in user has at least one UserOperatorRole for.
        Superusers can see all operators.
        """
        if self.request.auth and isinstance(self.request.auth, models.Operator):
            return models.Operator.objects.filter(id=self.request.auth.id)
        if self.request.user.is_superuser:
            return models.Operator.objects.all().prefetch_related("user_roles")
        return models.Operator.objects.filter(
            user_roles__user=self.request.user
        ).prefetch_related("user_roles")

    def get_serializer_class(self):
        return serializers.OperatorSerializer

    @action(detail=True, methods=["get"])
    def services(self, request, pk=None):
        """Return the list of services configured for this operator."""
        # Ensure the user has access to this operator
        self.get_object()

        services = models.Service.objects.filter(
            is_active=True,
            operatorserviceconfig__operator_id=pk,
        ).order_by("name")
        serializer = serializers.ServiceLightSerializer(services, many=True)
        return Response({"results": serializer.data})
