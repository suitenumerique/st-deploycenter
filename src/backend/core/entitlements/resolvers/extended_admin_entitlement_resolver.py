"""Extended admin entitlement resolver."""

from core.entitlements.resolvers.admin_entitlement_resolver import (
    AdminEntitlementResolver,
)
from core.entitlements.resolvers.entitlement_resolver import get_context_account

DEFAULT_POPULATION_THRESHOLD = 3500


def get_auto_admin_level(context):
    """Return the resolve level of the auto-admin path granting admin on the
    queried organization, or None.

    1. Email matches the organization's official contact (adresse_messagerie).
    2. Explicit auto_admin metadata on the subscription ("all" or "manual")
       overrides the population check.
    3. Population-based fallback when no explicit auto_admin choice has been made.

    The population threshold can be configured per service via
    service.config["auto_admin_population_threshold"]. Defaults to
    DEFAULT_POPULATION_THRESHOLD.
    """
    organization = context.get("organization")
    if not organization or not organization.siret:
        return None

    # Get the account email from the context or by looking up the account
    account_email = context.get("account_email") or ""
    if not account_email:
        account = get_context_account(context, throw_not_found=False)
        if account:
            account_email = account.email

    # 1. Email matches the organization's official contact
    if (
        account_email
        and organization.adresse_messagerie
        and account_email.lower() == organization.adresse_messagerie.lower()
    ):
        return "email_contact"

    # 2. Check auto_admin metadata on subscription
    service_subscription = context.get("service_subscription")
    auto_admin = (
        (service_subscription.metadata or {}).get("auto_admin")
        if service_subscription
        else None
    )

    if auto_admin == "all":
        return "auto_admin"

    if auto_admin == "manual":
        return None

    # 3. Fallback: organization population is under the threshold
    # All members of the organization are considered admins.
    auto_admin_population_threshold = DEFAULT_POPULATION_THRESHOLD
    if service_subscription:
        effective_config = service_subscription.get_effective_service_config()
        auto_admin_population_threshold = effective_config.get(
            "auto_admin_population_threshold", DEFAULT_POPULATION_THRESHOLD
        )
    if (
        organization.population is not None
        and organization.population < auto_admin_population_threshold
    ):
        return "population"

    return None


class ExtendedAdminEntitlementResolver(AdminEntitlementResolver):
    """
    Extended admin entitlement resolver.

    Extends the base admin resolver with the auto-admin paths of
    get_auto_admin_level.
    """

    def resolve(self, context):
        result = super().resolve(context)
        if result.get("is_admin"):
            return result

        level = get_auto_admin_level(context)
        if level:
            return {"is_admin": True, "is_admin_resolve_level": level}

        return result
