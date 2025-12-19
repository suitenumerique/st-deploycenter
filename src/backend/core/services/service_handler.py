"""Service handler."""

from core.models import ServiceSubscription

# pylint: disable=cyclic-import


class ServiceHandler:
    """
    Service handler.
    """

    def create_default_entitlements(self, service_subscription: ServiceSubscription):
        """
        Create default entitlements for the given service subscription.
        """
