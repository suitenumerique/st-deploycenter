from core import models
from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)


class PiggybackAccessEntitlementResolver(AccessEntitlementResolver):
    """
    Access entitlement resolver for a hidden service that piggy-backs on another
    service's subscription.

    Subclasses set ``SOURCE_SERVICE_TYPE`` to the service type whose active
    subscription gates access. We delegate to the parent
    ``_resolve_with_subscription`` after swapping the context's
    ``service_subscription`` for that source subscription, so the
    NO_ORGANIZATION / NOT_ACTIVATED branches stay in one place.
    """

    SOURCE_SERVICE_TYPE: str = ""

    def get_source_subscription(self, context):
        """Return the active source-service subscription for the org, or None."""
        organization = context.get("organization")
        if not organization:
            return None
        return (
            models.ServiceSubscription.objects.filter(
                organization=organization,
                service__type=self.SOURCE_SERVICE_TYPE,
                is_active=True,
            )
            .select_related("operator")
            .first()
        )

    def resolve(self, context):
        source_subscription = self.get_source_subscription(context)
        can_access, can_access_reason = self._resolve_with_subscription(
            {**context, "service_subscription": source_subscription}
        )
        res = {"can_access": can_access}
        if can_access_reason:
            res["can_access_reason"] = can_access_reason
        return res
