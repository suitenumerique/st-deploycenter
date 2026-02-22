"""Messages admin entitlement resolver."""

from django.db.models import Q

from core import models
from core.entitlements.resolvers.admin_entitlement_resolver import (
    AdminEntitlementResolver,
)


class MessagesAdminEntitlementResolver(AdminEntitlementResolver):
    """
    Replaces the base admin resolver with can_admin_maildomains:
    a list of mail domain names the user can admin across all organizations
    for the Messages service.
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
        )

        admin_org_ids = set()
        for account in admin_accounts:
            if "admin" in (account.roles or []):
                admin_org_ids.add(account.organization_id)
            service_link = account.service_links.filter(service=service).first()
            if service_link and "admin" in (service_link.roles or []):
                admin_org_ids.add(account.organization_id)

        if not admin_org_ids:
            return {"can_admin_maildomains": []}

        subscriptions = models.ServiceSubscription.objects.filter(
            organization_id__in=admin_org_ids,
            service=service,
            is_active=True,
        )

        domains = []
        for subscription in subscriptions:
            subscription_domains = (subscription.metadata or {}).get("domains") or []
            domains.extend(subscription_domains)

        return {"can_admin_maildomains": domains}
