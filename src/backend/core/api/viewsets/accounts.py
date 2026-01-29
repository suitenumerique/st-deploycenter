"""
API endpoints for Account model.
"""

from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, status, viewsets
from rest_framework import permissions as drf_permissions
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.api import permissions, serializers
from core.api.filters import AccountFilter
from core.authentication import ExternalManagementApiKeyAuthentication


class OrganizationAccountsViewSet(
    viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.ListModelMixin
):
    """ViewSet for OrganizationAccounts model.

    POST /api/v1.0/operators/<operator_id>/organizations/<organization_id>/accounts/
        Create the accounts for the given organization.

    GET /api/v1.0/operators/<operator_id>/organizations/<organization_id>/accounts/
        Get the accounts for the given organization.
        Supports filtering by type, role, and search by email/external_id.
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
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = AccountFilter
    search_fields = ["email", "external_id"]
    ordering_fields = ["email", "external_id", "type", "created_at"]
    ordering = ["created_at"]

    def get_queryset(self):
        return models.Account.objects.filter(
            organization=self.kwargs["organization_id"]
        ).prefetch_related("service_links", "service_links__service")

    def get_serializer_context(self):
        """Add organization_id to serializer context."""
        context = super().get_serializer_context()
        context["organization_id"] = self.kwargs["organization_id"]
        return context

    def create(self, request, *args, **kwargs):
        """Create or update an account (upsert via find_by_identifiers).

        If an existing account is found by external_id or email fallback,
        its roles are updated instead of creating a duplicate.
        Returns 201 on creation, 200 on update.
        """
        organization_id = self.kwargs["organization_id"]
        try:
            organization = models.Organization.objects.get(id=organization_id)
        except models.Organization.DoesNotExist as err:
            raise NotFound("Organization not found.") from err

        existing = models.Account.find_by_identifiers(
            organization=organization,
            account_type=request.data.get("type", "user"),
            external_id=request.data.get("external_id", ""),
            email=request.data.get("email", ""),
            reconcile_external_id=True,
        )

        if existing:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(organization=organization)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


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
