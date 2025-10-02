"""Permission handlers for the deploycenter core app."""

from django.core import exceptions

from rest_framework import permissions
from core import models

ACTION_FOR_METHOD_TO_PERMISSION = {
    "versions_detail": {"DELETE": "versions_destroy", "GET": "versions_retrieve"},
    "children": {"GET": "children_list", "POST": "children_create"},
}


class IsAuthenticated(permissions.BasePermission):
    """
    Allows access only to authenticated users. Alternative method checking the presence
    of the auth token to avoid hitting the database.
    """

    def has_permission(self, request, view):
        return bool(request.auth) or request.user.is_authenticated


class IsSuperUser(permissions.IsAdminUser):
    """Allows access only to superusers users."""

    def has_permission(self, request, view):
        return request.user and (request.user.is_superuser)


class IsAuthenticatedOrSafe(IsAuthenticated):
    """Allows access to authenticated users (or anonymous users but only on safe methods)."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return super().has_permission(request, view)


class IsSelf(IsAuthenticated):
    """
    Allows access only to authenticated users. Alternative method checking the presence
    of the auth token to avoid hitting the database.
    """

    def has_object_permission(self, request, view, obj):
        """Write permissions are only allowed to the user itself."""
        return obj == request.user


class IsOwnedOrPublic(IsAuthenticated):
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
    """

    def has_permission(self, request, view):
        operator = models.Operator.objects.get(id=view.kwargs['operator_id'])
        has_role = models.UserOperatorRole.objects.filter(operator=operator, user=request.user)
        return has_role


def user_has_role_in_organization(request, organization_id):
    organization = models.Organization.objects.get(id=organization_id)
    has_role = models.OperatorOrganizationRole.objects.filter(organization=organization, operator__user_roles__user=request.user).exists()
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
    """

    def has_permission(self, request, view):
        has_role = user_has_role_in_organization(request, view.kwargs['organization_id'])
        return has_role