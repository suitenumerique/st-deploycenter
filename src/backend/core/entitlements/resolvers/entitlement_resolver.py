import logging
from abc import ABC, abstractmethod

from core import models

logger = logging.getLogger(__name__)


def get_entitlements_by_priority(entitlements):
    """
    It sort entitlements by their hierarchy:
    user_override = (account_type="user", account_id="xyz)
    organization = (account_type="organization", account_id=None)
    user = (account_type="user", account_id=None)
    """
    user_override = None
    user = None
    organization = None

    for entitlement in entitlements:
        if entitlement.account_type == "user" and entitlement.account_id:
            user_override = entitlement
        elif entitlement.account_type == "user" and not entitlement.account_id:
            user = entitlement
        elif entitlement.account_type == "organization" and not entitlement.account_id:
            organization = entitlement
        else:
            raise ValueError(f"Invalid account type: {entitlement.account_type}")

    return {"user_override": user_override, "user": user, "organization": organization}


class MetricNotFoundError(Exception):
    """
    Exception raised when a metric is not found.
    """

    pass


class EntitlementResolver(ABC):
    """
    Base entitlement resolver.
    """

    resolve_level_prefix = ""

    def resolve(self, context):
        """
        Resolve the messages storage entitlement based on their priority.

        Basically in real terms it translates to:
        Your entitlement should comply to (this first one is the highest priority):
        - An entitlement for a specific user - can be considered as an blocking override (account_type="user", account_id="xyz")
        - An entitlement for organization (account_type="organization", account_id=None)
        - An entitlement for user (account_type="user", account_id=None)

        There is no entitlement for a specific organization (account_type="organization", account_id="xyz")
        because as an entitlement is already bounds to an organization via the service subscription. it would
        make no sense.

        For each level, we will fetch the appropriate metric and resolve the entitlement based on it.

        Example:
        We have a storage entitlement on drive that tells if a user can store new files.
        In order to be able to store new file it goes like:
        - If there is a user override (account_type="user", account_id="xyz"),
            we only consider this one. Whether it lowers or raises its storage compared
            to the default user or organization entitlement. It is an override.
        - If there is an organization entitlement (account_type="organization", account_id=None),
            we should make sure the entire organization have free storage left. If not,
            we should return false immediately.
        - We can now check the default user entitlement (account_type="user", account_id=None).
            At this point, there is no user override, and if there is an organization entitlement
            it tells that the organization still have free storage left. So we can finally check
            that the user has free storage left for the default user entitlement.

        This method also return in the object the last level at which the entitlement was compliant or not via
        "_reason_level" key.

        Example:
        {
            "can_store": True,
            "can_store_resolve_level": "user_override",
        }
        """

        entitlements = get_entitlements_by_priority(context["entitlements"])
        entitlement_user = entitlements.get("user")

        # The user override is the highest priority entitlement. Whether it
        # complies or not, we will return the result.
        if entitlement_user_override := entitlements.get("user_override"):
            metric = self._get_metric(context, entitlement_user_override)
            _, attributes = self._resolve_entitlement(
                context, entitlement_user_override, metric
            )
            return self._build_resolve_level(attributes, "user_override")

        # If there is an organization entitlement, it should first resolve anyway
        # before the generic user entitlement.
        if entitlement_organization := entitlements.get("organization"):
            metric = self._get_metric(context, entitlement_organization)
            compliant, attributes = self._resolve_entitlement(
                context, entitlement_organization, metric
            )
            # If there is a user entitlement and it this one does not comply, we can return directly.
            # Or if there is no user entitlement to run further, we can return directly in anyway.
            if not compliant or not entitlement_user:
                return self._build_resolve_level(attributes, "organization")

        # If there is a generic user entitlement, it should be the last one to resolve.
        if entitlement_user:
            metric = self._get_metric(context, entitlement_user)
            compliant, attributes = self._resolve_entitlement(
                context, entitlement_user, metric
            )
            return self._build_resolve_level(attributes, "user")

        raise ValueError(
            f"This should not happen, no user or organization entitlement could be resolved for the given context. "
            f"Service {context['service'].name}, organization {context['organization'].name}, "
            f"account type {context['account_type']}, account id {context['account_id']}"
        )

    def _get_metric(self, context, entitlement, filters):
        """
        Get the metric for the given entitlement in order to check against.
        This method is meant to be overridden by the child classes in order to add custom filters,
        especially the key filter in order to grab the correct metric.
        """

        if not filters:
            raise ValueError(
                "Filters are required, maybe you forgot to pass them to the get_metric method?"
                "Please mind to define the key filter."
            )

        if entitlement.account_type == "user":
            filters["account_type"] = entitlement.account_type
            filters["account_id"] = context["account_id"]
        elif entitlement.account_type == "organization":
            filters["account_type"] = entitlement.account_type
            filters["account_id"] = context["organization"].id
        else:
            raise ValueError(f"Invalid account type: {entitlement.account_type}")

        metric = (
            models.Metric.objects.filter(
                service=context["service"],
                organization=context["organization"],
                **filters,
            )
            .order_by("-timestamp")
            .first()
        )

        return metric

    def _build_resolve_level(self, attributes, resolve_level):
        """
        Build the resolve level string.
        """
        return {
            **attributes,
            f"{self.resolve_level_prefix}_resolve_level": resolve_level,
        }

    @abstractmethod
    def _resolve_entitlement(self, context, entitlement, metric):
        """
        Resolve the entitlement.
        This method is meant to be overridden by the child classes in order to implement the logic to resolve the entitlement.
        It should return a tuple with the first element being a boolean indicating if the entitlement complies with the metric or not,
        and the second element being a dictionary of attributes that will be returned in the resolve method.

        """
        pass

    def _log_metric_not_found_warning(self, context, entitlement):
        """
        Log a warning when a metric is not found.
        """
        logger.warning(
            "No metric found for entitlement %s - %s, service %s, organization %s, account type %s, account id %s",
            entitlement.id,
            entitlement.type,
            context["service"].name,
            context["organization"].name,
            entitlement.account_type,
            entitlement.account_id,
        )
