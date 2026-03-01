"""Messages admin entitlement resolver."""

from django.db.models import Prefetch, Q

from core import models
from core.entitlements.resolvers.admin_entitlement_resolver import (
    AdminEntitlementResolver,
)


class MessagesAdminEntitlementResolver(AdminEntitlementResolver):
    """
    Replaces the base admin resolver with can_admin_maildomains:
    a list of mail domain names the user can admin across all organizations
    for the Messages service.

    This resolver gathers all accounts matching the given email or id
    across organizations, and returns only the domain names (not org IDs)
    from active subscriptions where the user has admin access.

    Domain scoping: when a service link has scope={"domains": [...]}, the
    admin is restricted to only those domains (intersected with the
    subscription's actual domains). An empty scope means unrestricted.
    """

    def resolve(self, context):
        account_email = context.get("account_email") or ""
        account_id = context.get("account_id") or ""
        service = context.get("service")

        if not account_email and not account_id:
            return {"can_admin_maildomains": []}

        account_filter = Q()
        if account_id:
            account_filter |= Q(external_id=account_id)
        if account_email:
            account_filter |= Q(email=account_email)

        admin_accounts = models.Account.objects.filter(
            account_filter,
            type="user",
        ).prefetch_related(
            Prefetch(
                "service_links",
                queryset=models.AccountServiceLink.objects.filter(service=service),
                to_attr="service_links_for_service",
            )
        )

        # Build a dict: org_id -> allowed_domains (None = unrestricted)
        admin_org_domains = {}
        for account in admin_accounts:
            org_id = account.organization_id

            # Org-level admin → always unrestricted
            if "admin" in (account.roles or []):
                admin_org_domains[org_id] = None
                continue

            service_link = (
                account.service_links_for_service[0]
                if account.service_links_for_service
                else None
            )
            if service_link and "admin" in (service_link.roles or []):
                scope_domains = (service_link.scope or {}).get("domains")

                if scope_domains:
                    # Scoped: merge with existing restrictions for this org
                    existing = admin_org_domains.get(org_id)
                    if existing is None and org_id in admin_org_domains:
                        # Already unrestricted for this org, keep it
                        pass
                    elif existing is None:
                        # First time seeing this org, set scoped domains
                        admin_org_domains[org_id] = set(scope_domains)
                    else:
                        # Merge with existing scoped domains
                        admin_org_domains[org_id] = existing | set(scope_domains)
                else:
                    # Unscoped service admin → unrestricted
                    admin_org_domains[org_id] = None

        if not admin_org_domains:
            return {"can_admin_maildomains": []}

        subscriptions = models.ServiceSubscription.objects.filter(
            organization_id__in=admin_org_domains.keys(),
            service=service,
            is_active=True,
        )

        domains = []
        for subscription in subscriptions:
            subscription_domains = (subscription.metadata or {}).get("domains") or []
            allowed = admin_org_domains.get(subscription.organization_id)

            if allowed is None:
                # Unrestricted: include all subscription domains
                domains.extend(subscription_domains)
            else:
                # Restricted: intersect scope domains with subscription domains
                domains.extend(d for d in subscription_domains if d in allowed)

        return {"can_admin_maildomains": list(dict.fromkeys(domains))}
