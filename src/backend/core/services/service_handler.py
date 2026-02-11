"""Service handler."""

from core.models import ServiceSubscription

# pylint: disable=cyclic-import


class ServiceHandler:
    """
    Service handler.
    """

    # Default entitlements to create for this service type.
    # Each entry is a dict with: type, account_type, config
    DEFAULT_ENTITLEMENTS: list[dict] = []

    def get_default_entitlements(self) -> list[dict]:
        """
        Return the default entitlement configurations for this service type.
        Used by the API to expose defaults before subscription creation.
        """
        return self.DEFAULT_ENTITLEMENTS

    def create_default_entitlements(self, service_subscription: ServiceSubscription):
        """
        Create default entitlements for the given service subscription.
        Uses DEFAULT_ENTITLEMENTS as the source of truth.
        """
        for default in self.DEFAULT_ENTITLEMENTS:
            service_subscription.entitlements.get_or_create(
                type=default["type"],
                account_type=default["account_type"],
                account=None,
                defaults={"config": default["config"].copy()},
            )
