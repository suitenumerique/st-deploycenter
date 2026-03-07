from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)


class MeetAccessEntitlementResolver(AccessEntitlementResolver):
    """
    Meet access entitlement resolver.
    Returns can_create instead of can_access.
    """

    def resolve(self, context):
        """
        Resolve the access entitlement for meet.
        """
        can_access, can_access_reason = self._resolve_with_subscription(context)
        res = {"can_create": can_access}
        if can_access_reason:
            res["can_create_reason"] = can_access_reason
        return res
