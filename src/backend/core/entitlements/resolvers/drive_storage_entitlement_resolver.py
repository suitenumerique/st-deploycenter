class DriveStorageEntitlementResolver:
    """
    Drive storage entitlement resolver.
    """

    def resolve(self, entitlement, service_subscription, context):
        """
        Resolve the drive storage entitlement.
        """
        print('hi there')
        return {"can_upload": True}
