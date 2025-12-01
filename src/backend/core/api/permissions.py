"""Permission handlers for the deploycenter core app."""

import logging
import secrets

from django.core import exceptions

from rest_framework import permissions

from core import models

logger = logging.getLogger(__name__)

ACTION_FOR_METHOD_TO_PERMISSION = {
    "versions_detail": {"DELETE": "versions_destroy", "GET": "versions_retrieve"},
    "children": {"GET": "children_list", "POST": "children_create"},
}


class IsAuthenticatedWithAnyMethod(permissions.BasePermission):
    """
    Allows access only to authenticated users. Alternative method checking the presence
    of the auth token to avoid hitting the database.
    Supports both user authentication and external API key authentication.
    """

    def has_permission(self, request, view):
        # Check if authenticated via external API key (request.auth is Operator)
        if request.auth and isinstance(request.auth, models.Operator):
            return True
        # Check if authenticated via user
        return bool(request.user and request.user.is_authenticated)


class IsSuperUser(permissions.IsAdminUser):
    """Allows access only to superusers users."""

    def has_permission(self, request, view):
        return request.user and (request.user.is_superuser)


class IsAuthenticatedOrSafe(IsAuthenticatedWithAnyMethod):
    """Allows access to authenticated users (or anonymous users but only on safe methods)."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return super().has_permission(request, view)


class IsSelf(IsAuthenticatedWithAnyMethod):
    """
    Allows access only to authenticated users. Alternative method checking the presence
    of the auth token to avoid hitting the database.
    """

    def has_object_permission(self, request, view, obj):
        """Write permissions are only allowed to the user itself."""
        return obj == request.user


class IsOwnedOrPublic(IsAuthenticatedWithAnyMethod):
    """
    Allows access to authenticated users only for objects that are owned or not related
    to any user via the "owner" field.
    """

    def has_object_permission(self, request, view, obj):
        """Unsafe permissions are only allowed for the owner of the object."""
        if obj.owner == request.user:
            return True

        if request.method in permissions.SAFE_METHODS and obj.owner is None:
            return True

        try:
            return obj.user == request.user
        except exceptions.ObjectDoesNotExist:
            return False


class OperatorAccessPermission(permissions.BasePermission):
    """
    Allows access only to authenticated users with a role in a operators's parent organization.
    Used for nested /operators/<operator_id>/* endpoints.
    Supports both user authentication and external API key authentication.
    """

    def has_permission(self, request, view):
        # If authenticated via external API key, check if the operator matches
        if request.auth and isinstance(request.auth, models.Operator):
            operator = request.auth
            return str(operator.id) == str(view.kwargs["operator_id"])

        # Regular user authentication
        operator = models.Operator.objects.get(id=view.kwargs["operator_id"])
        has_role = models.UserOperatorRole.objects.filter(
            operator=operator, user=request.user
        ).exists()
        return has_role


def user_has_role_in_organization(request, organization_id):
    """Check if the user has a role in a organization's operator."""
    organization = models.Organization.objects.get(id=organization_id)
    has_role = models.OperatorOrganizationRole.objects.filter(
        organization=organization, operator__user_roles__user=request.user
    ).exists()
    return has_role


class OrganizationAccessPermission(permissions.BasePermission):
    """
    Allows access only to authenticated users with a role in a organizations's operator.
    """

    def has_object_permission(self, request, view, obj):
        """
        Check if the user has a role in a organizations's operator.
        """
        has_role = user_has_role_in_organization(request, obj.id)
        return has_role


class ParentOrganizationAccessPermission(permissions.BasePermission):
    """
    Allows access only to authenticated users with a role in a organizations's parent operator.
    Used for nested /organizations/<organization_id>/* endpoints.
    Supports both user authentication and external API key authentication.
    """

    def has_permission(self, request, view):
        organization_id = view.kwargs.get("organization_id")
        if not organization_id:
            return False

        # If authenticated via external API key, check if operator manages the organization
        if request.auth and isinstance(request.auth, models.Operator):
            operator = request.auth
            operator_id = view.kwargs.get("operator_id")

            # Verify the operator_id in URL matches the authenticated operator
            if operator_id and str(operator.id) != str(operator_id):
                return False

            # Check if operator manages the organization
            return models.OperatorOrganizationRole.objects.filter(
                organization_id=organization_id, operator=operator
            ).exists()

        # Regular user authentication
        return user_has_role_in_organization(request, organization_id)


class ServiceAuthenticationPermission(permissions.BasePermission):
    """
    Allows access only to authenticated users with a service authentication.
    """

    def has_permission(self, request, view):
        api_key_header = request.headers.get("X-Service-Auth")
        if not api_key_header:
            return False

        api_key = api_key_header.split(" ")[1]

        # Check if the service matches.
        target_service = models.Service.objects.filter(
            id=request.query_params.get("service_id")
        ).first()
        if not target_service:
            return False

        # Check if the API key is valid.
        service_api_key = target_service.config.get("entitlements_api_key", "")
        if not secrets.compare_digest(service_api_key, api_key):
            return False

        return True
