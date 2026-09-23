"""BAL admin entitlement resolver."""

from django.db.models import Prefetch, Q

from core import models
from core.entitlements.resolvers.admin_entitlement_resolver import (
    AdminEntitlementResolver,
)
from core.entitlements.resolvers.extended_admin_entitlement_resolver import (
    get_auto_admin_level,
)
from core.services import bal as bal_service


class BalAdminEntitlementResolver(AdminEntitlementResolver):
    """
    Replaces the base admin resolver with can_admin_communes: a dict of
    ``insee: [channels]`` listing the communes (and address channels) the
    queried user may administer for the BAL service, across all organizations.

    Sources of access, unioned per commune. Each grants channels on every
    commune the organization covers (see core.services.bal.get_covered_communes):

    - Organization-level ``admin`` role on an account: all channels.
    - BAL service-link ``admin``: the channels of the link's scope
      (see core.services.bal.parse_scope).
    - Operator admin passthrough, as in the Messages resolver.
    - For the queried organization only, when it is a commune with an active
      BAL subscription: the ADC/ESD auto-admin paths (get_auto_admin_level).

    Because this resolver aggregates admin rights across *all* organizations,
    it must run even when the queried organization has no active subscription.
    """

    runs_without_active_subscription = True

    def resolve(self, context):
        account_email = context.get("account_email") or ""
        account_id = context.get("account_id") or ""
        service = context.get("service")

        if not account_email and not account_id:
            return {"can_admin_communes": {}}

        all_channels = frozenset(bal_service.CHANNELS)
        # org_id -> set(channels)
        org_access = {}

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
                queryset=models.AccountServiceLink.objects.filter(
                    service=service, role="admin"
                ),
                to_attr="bal_admin_links",
            )
        )

        for account in admin_accounts:
            if "admin" in (account.roles or []):
                channels = all_channels
            elif account.bal_admin_links:
                channels = bal_service.parse_scope(account.bal_admin_links[0].scope)
            else:
                continue
            org_access.setdefault(account.organization_id, set()).update(channels)

        if account_email:
            operator_admin_org_ids = (
                models.OperatorOrganizationRole.objects.filter(
                    role="admin",
                    operator_admins_have_admin_role=True,
                    operator__user_roles__role="admin",
                    operator__user_roles__user__email=account_email,
                    organization__service_subscriptions__service=service,
                    organization__service_subscriptions__is_active=True,
                )
                .values_list("organization_id", flat=True)
                .distinct()
            )
            for org_id in operator_admin_org_ids:
                org_access[org_id] = all_channels

        organization = context.get("organization")
        subscription = context.get("service_subscription")
        if (
            organization
            and organization.type == "commune"
            and subscription
            and subscription.is_active
            and get_auto_admin_level(context)
        ):
            org_access[organization.id] = all_channels

        result = {}
        granting_org_ids = [
            org_id for org_id, channels in org_access.items() if channels
        ]
        for org in models.Organization.objects.filter(id__in=granting_org_ids):
            for insee in bal_service.get_covered_communes(org, service):
                result.setdefault(insee, set()).update(org_access[org.id])

        return {
            "can_admin_communes": {
                insee: [c for c in bal_service.CHANNELS if c in channels]
                for insee, channels in sorted(result.items())
            }
        }
