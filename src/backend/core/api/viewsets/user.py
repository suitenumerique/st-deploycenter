"""API ViewSet for User model."""

import rest_framework as drf
from rest_framework import viewsets

from .. import permissions, serializers
from core import models


class UserViewSet(viewsets.GenericViewSet, drf.mixins.UpdateModelMixin):
    """ViewSet for User model."""

    serializer_class = serializers.UserSerializer
    permission_classes = [permissions.IsSelf]
    queryset = models.User.objects.all()

    @drf.decorators.action(
        detail=False,
        methods=["get"],
        url_name="me",
        url_path="me",
        permission_classes=[permissions.IsAuthenticated],
    )
    def get_me(self, request):
        """
        Return information on currently logged user
        """
        context = {"request": request}
        return drf.response.Response(
            self.serializer_class(request.user, context=context).data
        )
