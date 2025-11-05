from core import models
from core.entitlements.resolvers.drive_storage_entitlement_resolver import (
    DriveStorageEntitlementResolver,
)

TYPE_TO_RESOLVER = {
    models.Entitlement.EntitlementType.DRIVE_STORAGE: DriveStorageEntitlementResolver,
}


def get_entitlement_resolver(entitlement_type: models.Entitlement.EntitlementType):
    """
    Get the entitlement resolver for the given entitlement type.
    """
    resolver_class = TYPE_TO_RESOLVER.get(entitlement_type)
    if resolver_class is None:
        raise ValueError(f"No resolver found for entitlement type: {entitlement_type}")
    return resolver_class()
