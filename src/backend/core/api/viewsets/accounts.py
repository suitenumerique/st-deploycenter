"""
API endpoints for Account model.
"""

from django.shortcuts import get_object_or_404

from rest_framework import mixins, viewsets
from rest_framework import permissions as drf_permissions
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.api import permissions, serializers
from core.authentication import ExternalManagementApiKeyAuthentication


class OrganizationAccountsViewSet(
    viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.ListModelMixin
):
    """ViewSet for OrganizationAccounts model.

    POST /api/v1.0/operators/<operator_id>/organizations/<organization_id>/accounts/
        Create the accounts for the given organization.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/accounts/
        Get the accounts for the given organization.
    """

    queryset = models.Account.objects.all()
    serializer_class = serializers.AccountSerializer
    authentication_classes = [
        ExternalManagementApiKeyAuthentication,
    ] + [*api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission,
    ]

    def get_queryset(self):
        return models.Account.objects.filter(
            organization=self.kwargs["organization_id"]
        )

    def get_serializer_context(self):
        """Add organization_id to serializer context."""
        context = super().get_serializer_context()
        context["organization_id"] = self.kwargs["organization_id"]
        return context

    def perform_create(self, serializer):
        """Set the organization when creating an account."""
        organization_id = self.kwargs["organization_id"]
        try:
            organization = models.Organization.objects.get(id=organization_id)
        except models.Organization.DoesNotExist as err:
            raise NotFound("Organization not found.") from err
        serializer.save(organization=organization)


class AccountViewSet(
    viewsets.GenericViewSet, mixins.RetrieveModelMixin, mixins.UpdateModelMixin
):
    """ViewSet for Account model.

    GET /api/v1.0/accounts/<account_id>/
        Get the account for the given account id.

    PATCH /api/v1.0/accounts/<account_id>/
        Partially update the account for the given account id.

    PATCH /api/v1.0/accounts/<account_id>/services/<service_id>/
        Partially update the service link for the given account and service.
    """

    queryset = models.Account.objects.all()
    serializer_class = serializers.AccountSerializer

    class AccountPermission(drf_permissions.BasePermission):
        """Permission class for Account model."""

        def has_object_permission(self, request, view, obj):
            return permissions.request_has_role_in_organization(
                request, obj.organization.id
            )

    authentication_classes = [
        ExternalManagementApiKeyAuthentication,
    ] + [*api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        AccountPermission,
    ]

    @action(detail=True, methods=["patch"], url_path="services/(?P<service_id>[^/.]+)")
    def service_link_update(self, request, *args, **kwargs):
        """Partially update the service link for the given account and service."""
        account = self.get_object()
        service = get_object_or_404(models.Service, id=kwargs["service_id"])
        service_link = account.service_links.filter(service=service).first()
        if not service_link:
            service_link = account.service_links.create(service=service)
        serializer = serializers.AccountServiceLinkSerializer(
            service_link, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
