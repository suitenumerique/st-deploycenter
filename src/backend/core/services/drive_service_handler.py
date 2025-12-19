"""Drive service handler."""

from core.models import Entitlement, ServiceSubscription

from .service_handler import ServiceHandler


class DriveServiceHandler(ServiceHandler):
    """
    Drive service handler.
    """

    def create_default_entitlements(self, service_subscription: ServiceSubscription):
        """
        Check the default entitlements for the given service subscription.
        """
        if service_subscription.entitlements.filter(
            type=Entitlement.EntitlementType.DRIVE_STORAGE
        ).exists():
            return
        service_subscription.entitlements.create(
            type=Entitlement.EntitlementType.DRIVE_STORAGE,
            config={
                "max_storage": 1000 * 1000 * 1000 * 10,  # 10GB
            },
            account_type="user",
            account_id="",
        )
