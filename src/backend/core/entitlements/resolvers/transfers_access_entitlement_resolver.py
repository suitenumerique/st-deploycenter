from core.entitlements.resolvers.piggyback_access_entitlement_resolver import (
    PiggybackAccessEntitlementResolver,
)


class TransfersAccessEntitlementResolver(PiggybackAccessEntitlementResolver):
    """
    Transfers piggy-backs on Drive: access requires an active drive subscription
    on the organization.
    """

    SOURCE_SERVICE_TYPE = "drive"
