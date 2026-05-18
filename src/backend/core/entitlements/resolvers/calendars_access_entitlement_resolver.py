from core.entitlements.resolvers.piggyback_access_entitlement_resolver import (
    PiggybackAccessEntitlementResolver,
)


class CalendarsAccessEntitlementResolver(PiggybackAccessEntitlementResolver):
    """
    Calendars piggy-backs on Messages: access requires an active messages
    subscription on the organization.
    """

    SOURCE_SERVICE_TYPE = "messages"
