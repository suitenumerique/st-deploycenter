from core import models


def order_entitlements_by_priority(entitlements):
    """
    This orders entitlements by this order of priority (the first one is the highest priority):
    (account_type="user", account_id="xyz)
    (account_type="organization", account_id=None)
    (account_type="user", account_id=None)

    Basically in real terms it translations to this:
    Your entitlement should comply to (this first one is the highest priority):
    - An entitlement for a specific user - can be considered as an override (account_type="user", account_id="xyz")
    - An entitlement for organization (account_type="organization", account_id=None)
    - An entitlement for user (account_type="user", account_id=None)

    There is no entitlement for a specific organization because as an entitlement is
    already bounds to an organization via the service subscription.
    """
    return {
        user_override: None,
        user: None,
        organization: None,
    }
    


class MessagesStorageEntitlementResolver:
    """
    Messages storage entitlement resolver.
    """

    reason_prefix = ""


    def _get_metric(self, context, entitlement):
        """
        Get the metric for the given entitlement in order to check against.
        """

        filters = {}
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
                key="storage_used",
                **filters,
            )
            .order_by("-timestamp")
            .first()
        )

        return metric

    def resolve(self, context):
        """
        Resolve the messages storage entitlement.

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
        """
        

        entitlements = order_entitlements_by_priority(context["entitlements"])

        # The user override is the highest priority entitlement. Whether it
        # resolves or not, we will return the result.
        if entitlement_user_override := entitlements.get("user_override"):
            metric = self._get_metric(context, entitlement_user_override)
            _, attributes = self.resolve_entitlement(context, entitlement_user_override, metric)
            return {**attributes, f"{self.reason_prefix}_reason_level": "user_override"}

        # If there is an organization entitlement, it should first resolve anyway
        # before the generic user entitlement.
        if entitlement_organization := entitlements.get("organization"):
            metric = self._get_metric(context, entitlement_organization)
            resolves, attributes = self.resolve_entitlement(context, entitlement_organization, metric)
            if not resolves:
                return {**attributes, f"{self.reason_prefix}_reason_level": "organization"}

        # If there is a generic user entitlement, it should be the last one to resolve.
        if entitlement_user := entitlements.get("user"):
            metric = self._get_metric(context, entitlement_user)
            resolves, attributes = self.resolve_entitlement(context, entitlement_user, metric)
            return {**attributes, f"{self.reason_prefix}_reason_level": "user"}

        raise ValueError(
            f"This should not happen, no user or organization entitlement could be resolved for the given context. "
            f"Service {context['service'].name}, organization {context['organization'].name}, "
            f"account type {context['account_type']}, account id {context['account_id']}"
        )

    # Child method, abstract.
    def resolve_entitlement(self, context, entitlement, metric):
        """
        Resolve the messages storage entitlement.
        """
        max_storage = entitlement.config.get("max_storage") or 0
        if max_storage == 0:
            return (True, {"can_store": True})
        if metric.value >= max_storage:
            return (False, {"can_store": False})
        return (True, {"can_store": True})
