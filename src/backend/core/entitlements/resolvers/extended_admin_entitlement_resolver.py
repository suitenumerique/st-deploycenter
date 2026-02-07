"""Extended admin entitlement resolver."""

from core.entitlements.resolvers.admin_entitlement_resolver import (
    AdminEntitlementResolver,
)
from core.entitlements.resolvers.entitlement_resolver import get_context_account

DEFAULT_POPULATION_THRESHOLD = 3500


class ExtendedAdminEntitlementResolver(AdminEntitlementResolver):
    """
    Extended admin entitlement resolver.

    Extends the base admin resolver with additional ways to be admin:
    1. Email matches the organization's official contact (adresse_messagerie).
    2. Explicit auto_admin metadata on the subscription ("all" or "manual") overrides population check.
    3. Population-based fallback when no explicit auto_admin choice has been made.

    The population threshold can be configured per service via
    service.config["auto_admin_population_threshold"]. Defaults to DEFAULT_POPULATION_THRESHOLD.
    """

    def resolve(self, context):
        result = super().resolve(context)
        if result.get("is_admin"):
            return result

        organization = context.get("organization")
        if not organization or not organization.siret:
            return result

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
            return {"is_admin": True, "is_admin_resolve_level": "email_contact"}

        # 2. Check auto_admin metadata on subscription
        service_subscription = context.get("service_subscription")
        auto_admin = (
            (service_subscription.metadata or {}).get("auto_admin")
            if service_subscription
            else None
        )

        if auto_admin == "all":
            return {"is_admin": True, "is_admin_resolve_level": "auto_admin"}

        if auto_admin == "manual":
            return result

        # 3. Fallback: organization population is under the threshold
        # All members of the organization are considered admins.
        service = context.get("service")
        auto_admin_population_threshold = (
            (service.config or {}).get(
                "auto_admin_population_threshold", DEFAULT_POPULATION_THRESHOLD
            )
            if service
            else DEFAULT_POPULATION_THRESHOLD
        )
        if (
            organization.population is not None
            and organization.population < auto_admin_population_threshold
        ):
            return {"is_admin": True, "is_admin_resolve_level": "population"}

        return result
