from core.entitlements.resolvers.entitlement_resolver import EntitlementResolver


class MessagesStorageEntitlementResolver(EntitlementResolver):
    """
    Messages storage entitlement resolver.
    """

    resolve_level_prefix = "can_store"

    def _resolve_entitlement(self, context, entitlement, metric):
        """
        Resolve the messages storage entitlement.
        """
        if not metric:
            self._log_metric_not_found_warning(context, entitlement)
            return (False, {"can_store": False})

        max_storage = entitlement.config.get("max_storage") or 0
        storage_used = int(metric.value) if metric else 0

        if max_storage == 0:
            return (
                True,
                {"can_store": True, "max_storage": 0, "storage_used": storage_used},
            )
        if storage_used > max_storage:
            return (
                False,
                {
                    "can_store": False,
                    "max_storage": max_storage,
                    "storage_used": storage_used,
                },
            )
        return (
            True,
            {
                "can_store": True,
                "max_storage": max_storage,
                "storage_used": storage_used,
            },
        )

    def _get_metric(self, context, entitlement):
        """
        Get the metric for the given entitlement.
        """
        return super()._get_metric(
            context,
            entitlement,
            {
                "key": "storage_used",
            },
        )
