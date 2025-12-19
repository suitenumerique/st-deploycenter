"""Messages service handler."""

from core.models import Entitlement, ServiceSubscription

from .service_handler import ServiceHandler


class MessagesServiceHandler(ServiceHandler):
    """
    Messages service handler.
    """

    def create_default_entitlements(self, service_subscription: ServiceSubscription):
        """
        Create default messages entitlements for the service subscription.
        """

        # Mailbox level entitlement.
        if not service_subscription.entitlements.filter(
            type=Entitlement.EntitlementType.MESSAGES_STORAGE,
            account_type="mailbox",
            account_id="",
        ).exists():
            service_subscription.entitlements.create(
                type=Entitlement.EntitlementType.MESSAGES_STORAGE,
                config={
                    "max_storage": 1000 * 1000 * 1000 * 5,  # 5GB
                },
                account_type="mailbox",
                account_id="",
            )

        # If there is no organization level entitlement, create one.
        # Organization level entitlement.
        if not service_subscription.entitlements.filter(
            type=Entitlement.EntitlementType.MESSAGES_STORAGE,
            account_type="organization",
            account_id="",
        ).exists():
            service_subscription.entitlements.create(
                type=Entitlement.EntitlementType.MESSAGES_STORAGE,
                config={
                    "max_storage": 1000 * 1000 * 1000 * 50,  # 50GB
                },
                account_type="organization",
                account_id="",
            )
