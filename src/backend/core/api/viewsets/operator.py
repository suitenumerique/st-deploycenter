"""
API endpoints for Operator model.
"""

from rest_framework import viewsets

from core import models

from .. import permissions, serializers


class OperatorViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Operator model.

    GET /api/v1.0/operators/
        Return the list of operators based on the user's permissions.

    GET /api/v1.0/operators/<operator_id>
        Return the operator with the given id based on the user's permissions.
    """

    queryset = models.Operator.objects.all()
    serializer_class = serializers.OperatorSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Return only operators that the logged-in user has at least one UserOperatorRole for.
        """
        return models.Operator.objects.filter(
            user_roles__user=self.request.user
        ).prefetch_related("user_roles")

    def get_serializer_class(self):
        return serializers.OperatorSerializer
