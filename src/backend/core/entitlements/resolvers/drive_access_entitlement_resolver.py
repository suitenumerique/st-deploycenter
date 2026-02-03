class DriveAccessEntitlementResolver:
    """
    Drive access entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the drive access entitlement.
        We always return true for the drive access entitlement even without a subscription.
        We want users to be able to access the drive service even without a subscription.
        But in this case, we will not return any entitlement, so the user will not be able to upload files.
        """
        return {
            "can_access": True,
        }
