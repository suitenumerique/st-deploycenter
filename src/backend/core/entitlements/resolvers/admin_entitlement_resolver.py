from core.entitlements.resolvers.entitlement_resolver import (
    EntitlementResolver,
    get_context_account,
)


class AdminEntitlementResolver(EntitlementResolver):
    """
    Admin entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the admin entitlement.
        """
        account = get_context_account(context, False)
        # Should not happen, but just in case.
        if not account:
            return {"is_admin": False, "is_admin_reason": "no_account"}
        # If the account has the admin role at the organization level, it is compliant.
        if "admin" in account.roles:
            return {"is_admin": True, "is_admin_resolve_level": "organization"}

        service_link = account.service_links.filter(service=context["service"]).first()
        if service_link and "admin" in service_link.roles:
            return {"is_admin": True, "is_admin_resolve_level": "service"}

        return {"is_admin": False, "is_admin_reason": "no_admin_role"}
