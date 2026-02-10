"""Messages service handler."""

from core.models import Entitlement

from .service_handler import ServiceHandler


class MessagesServiceHandler(ServiceHandler):
    """
    Messages service handler.
    """

    DEFAULT_ENTITLEMENTS = [
        {
            "type": Entitlement.EntitlementType.MESSAGES_STORAGE,
            "account_type": "mailbox",
            "config": {"max_storage": 1000 * 1000 * 1000 * 5},  # 5GB
        },
        {
            "type": Entitlement.EntitlementType.MESSAGES_STORAGE,
            "account_type": "organization",
            "config": {"max_storage": 1000 * 1000 * 1000 * 50},  # 50GB
        },
    ]
