
from rest_framework import viewsets
from .. import permissions, serializers
from core import models
import rest_framework as drf

class OperatorOrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        operator = models.Operator.objects.get(id=self.kwargs['resource_id'])
        has_role = models.UserOperatorRole.objects.filter(operator=operator, user=self.request.user)
        # We need to make sure that the user has at least one role for the operator.
        if not has_role:
            raise drf.exceptions.NotFound
        return models.Organization.objects.filter(operators__id=self.kwargs['resource_id']).all()

class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.OrganizationAccessPermission]

    def get_queryset(self):
        return models.Organization.objects.all()

    def list(self, request, *args, **kwargs):
        raise drf.exceptions.NotFound