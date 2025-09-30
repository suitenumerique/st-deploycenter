
from rest_framework import viewsets
from .. import permissions, serializers
from core import models

class OperatorViewSet(viewsets.ReadOnlyModelViewSet):   
    queryset = models.Operator.objects.all()
    serializer_class = serializers.OperatorSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Return only operators that the logged-in user has at least one UserOperatorRole for.
        """
        return models.Operator.objects.filter(
            user_roles__user=self.request.user
        ).prefetch_related('user_roles')

    def get_serializer_class(self):
        return serializers.OperatorSerializer