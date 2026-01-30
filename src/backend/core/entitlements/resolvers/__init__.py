from core import models
from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)
from core.entitlements.resolvers.drive_access_entitlement_resolver import (
    DriveAccessEntitlementResolver,
)
from core.entitlements.resolvers.drive_storage_entitlement_resolver import (
    DriveStorageEntitlementResolver,
)
from core.entitlements.resolvers.messages_storage_entitlement_resolver import (
    MessagesStorageEntitlementResolver,
)

TYPE_TO_RESOLVER = {
    models.Entitlement.EntitlementType.DRIVE_STORAGE: DriveStorageEntitlementResolver,
    models.Entitlement.EntitlementType.MESSAGES_STORAGE: MessagesStorageEntitlementResolver,
}


TYPE_TO_ACCESS_RESOLVER = {
    "drive": DriveAccessEntitlementResolver,
}


def get_entitlement_resolver(entitlement_type: models.Entitlement.EntitlementType):
    """
    Get the entitlement resolver for the given entitlement type.
    """
    resolver_class = TYPE_TO_RESOLVER.get(entitlement_type)
    if resolver_class is None:
        raise ValueError(f"No resolver found for entitlement type: {entitlement_type}")
    return resolver_class()


def get_access_entitlement_resolver(service: models.Service):
    """
    Get the access entitlement resolver. If not found, return the default access entitlement resolver.
    """
    resolver_class = TYPE_TO_ACCESS_RESOLVER.get(service.type)
    if resolver_class:
        return resolver_class()
    return AccessEntitlementResolver()
