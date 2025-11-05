import logging

from core import models

logger = logging.getLogger(__name__)


class DriveStorageEntitlementResolver:
    """
    Drive storage entitlement resolver.
    """

    def resolve(self, context):
        """
        Resolve the drive storage entitlement.
        """
        metric = (
            models.Metric.objects.filter(
                service=context["service"],
                organization=context["organization"],
                account_type=context["account_type"],
                account_id=context["account_id"],
                key="storage_used",
            )
            .order_by("-timestamp")
            .first()
        )
        if not metric:
            logger.warning(
                "No metrics found for service %s, organization %s, account type %s, account id %s",
                context["service"].name,
                context["organization"].name,
                context["account_type"],
                context["account_id"],
            )
            return {"can_upload": False}

        entitlement = context["entitlement"]
        max_storage = entitlement.config.get("max_storage")
        if not max_storage:
            logger.warning(
                "No max storage size configured for entitlement %s", entitlement.id
            )
            return {"can_upload": False}

        if metric.value > max_storage:
            return {"can_upload": False}

        return {"can_upload": True}
