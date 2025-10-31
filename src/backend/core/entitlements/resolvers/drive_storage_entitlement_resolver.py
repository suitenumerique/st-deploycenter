class DriveStorageEntitlementResolver:
    """
    Drive storage entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the drive storage entitlement.
        """
        return {"can_upload": True}
