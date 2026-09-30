"""Entitlement resolver for the administration services."""

from core import models
from core.entitlements.resolvers.entitlement_resolver import (
    EntitlementResolver,
    get_context_account,
)


def get_admin_operators(account_email):
    """Return the active operators whose admins include a user matching
    account_email (case-insensitive), as a list of {"name", "id", "url"} sorted
    by name.
    """
    if not account_email:
        return []

    operators = (
        models.Operator.objects.filter(
            is_active=True,
            user_roles__role="admin",
            user_roles__user__email__iexact=account_email,
        )
        .order_by("name", "id")
        .values("name", "id", "url")
        .distinct()
    )
    return [
        {"name": op["name"], "id": str(op["id"]), "url": op["url"]} for op in operators
    ]


class AdminEntitlementResolver(EntitlementResolver):
    """
    Admin entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the admin entitlement.
        """
        account = get_context_account(context, False)

        if account:
            if "admin" in account.roles:
                return {"is_admin": True, "is_admin_resolve_level": "organization"}

            if account.service_links.filter(
                service=context["service"], role="admin"
            ).exists():
                return {"is_admin": True, "is_admin_resolve_level": "service"}

        if self._is_operator_admin(context):
            return {"is_admin": True, "is_admin_resolve_level": "operator"}

        return {"is_admin": False}

    @staticmethod
    def _is_operator_admin(context):
        """Check if the user is an operator admin with passthrough enabled.

        Returns True when:
        - account_email is provided
        - The organization has an OperatorOrganizationRole with role="admin"
          and operator_admins_have_admin_role=True
        - The operator of that role has a UserOperatorRole with role="admin"
          for a user whose email matches account_email (case-insensitive)
        - The organization has an active subscription for the queried service
        """
        account_email = context.get("account_email") or ""
        if not account_email:
            return False

        organization = context.get("organization")
        service = context.get("service")
        if not organization or not service:
            return False

        return models.OperatorOrganizationRole.objects.filter(
            role="admin",
            operator_admins_have_admin_role=True,
            organization=organization,
            operator__user_roles__role="admin",
            operator__user_roles__user__email__iexact=account_email,
            organization__service_subscriptions__service=service,
            organization__service_subscriptions__is_active=True,
        ).exists()
