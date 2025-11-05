class AccessEntitlementResolver:
    """
    Access entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the access entitlement.
        """
        return {"can_access": bool(context.get("service_subscription"))}
