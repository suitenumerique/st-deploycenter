from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)


class DriveAccessEntitlementResolver(AccessEntitlementResolver):
    """
    Drive access entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the drive access entitlement.
        We always return true for the drive access entitlement even without a subscription.
        We want users to be able to access the drive service even without a subscription.
        But in this case, we will not return any entitlement, so the user will not be able to upload files.

        The strange behavior for can_upload is because, when there is no organization or no active subscription,
        the can_upload entitlement is not resolved, but we want to give information about the reason why
        the user cannot upload files. In some case on Drive we need to display a message to the user to explain
        that he cannot upload files because he is not subscribed to the service, not especially for the case
        that his storage is full.
        """
        parent_output = super().resolve(context)
        output = {
            "can_access": True,
        }
        # Means there is no organization or no active subscription.
        if not parent_output["can_access"]:
            output["can_upload"] = False
            output["can_upload_reason"] = parent_output["can_access_reason"]
        return output
