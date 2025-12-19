import logging
from enum import StrEnum

logger = logging.getLogger(__name__)


class AccessEntitlementResolver:
    """
    Access entitlement resolver.
    """

    class Reason(StrEnum):
        NO_ORGANIZATION = "no_organization"
        NOT_ACTIVATED = "not_activated"

    def _resolve_with_subscription(self, context):
        """
        Resolve the access entitlement with a subscription.
        """
        if not context.get("organization"):
            logger.warning(
                "No organization found for service %s, account type %s, account id %s, siret %s",
                context["service"].name,
                context["account_type"],
                context["account_id"],
                context["siret"],
            )
            return (False, self.Reason.NO_ORGANIZATION)

        if (
            context.get("service_subscription")
            and context.get("service_subscription").is_active
        ):
            return (True, None)

        return (False, self.Reason.NOT_ACTIVATED)

    def resolve(self, context):
        """
        Resolve the access entitlement.
        """
        can_access, can_access_reason = self._resolve_with_subscription(context)
        return {
            "can_access": can_access,
            "can_access_reason": can_access_reason,
        }
