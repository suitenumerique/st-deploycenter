from core import models
from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)


class TransfersAccessEntitlementResolver(AccessEntitlementResolver):
    """
    Transfers access entitlement resolver.

    Transfers is a hidden service piggy-backing on Drive: an organization can
    access it only if it already has an active subscription to a Drive service.
    We delegate to the parent ``_resolve_with_subscription`` after swapping the
    context's ``service_subscription`` for the organization's drive subscription,
    so the NO_ORGANIZATION / NOT_ACTIVATED branches stay in one place.
    """

    def resolve(self, context):
        drive_subscription = None
        if context.get("organization"):
            drive_subscription = models.ServiceSubscription.objects.filter(
                organization=context["organization"],
                service__type="drive",
                is_active=True,
            ).first()

        can_access, can_access_reason = self._resolve_with_subscription(
            {**context, "service_subscription": drive_subscription}
        )
        res = {"can_access": can_access}
        if can_access_reason:
            res["can_access_reason"] = can_access_reason
        return res
