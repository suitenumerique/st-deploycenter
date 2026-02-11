"""Drive service handler."""

from core.models import Entitlement

from .service_handler import ServiceHandler


class DriveServiceHandler(ServiceHandler):
    """
    Drive service handler.
    """

    DEFAULT_ENTITLEMENTS = [
        {
            "type": Entitlement.EntitlementType.DRIVE_STORAGE,
            "account_type": "user",
            "config": {"max_storage": 1000 * 1000 * 1000 * 10},  # 10GB
        },
    ]
