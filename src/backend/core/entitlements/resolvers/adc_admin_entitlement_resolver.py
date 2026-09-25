"""ADC admin entitlement resolver."""

from django.db.models import Q

from core import models
from core.entitlements.resolvers.extended_admin_entitlement_resolver import (
    ExtendedAdminEntitlementResolver,
)


class AdcAdminEntitlementResolver(ExtendedAdminEntitlementResolver):
    """
    Extends the ADC admin resolver with can_admin_collectivites: a sorted list of
    the SIRENs of the communes the queried user may administer as an
    operator admin, across all organizations.

    The user is matched by account_email (case-insensitive) against the
    UserOperatorRole admins of active operators. Such an operator grants every
    commune it has an OperatorOrganizationRole on. Service subscriptions and
    operator_admins_have_admin_role are not considered.

    Because can_admin_collectivites spans all organizations, this resolver also runs
    when the queried organization has no active subscription. is_admin is
    only resolved when it has one.
    """

    runs_without_active_subscription = True

    def resolve(self, context):
        subscription = context.get("service_subscription")
        result = (
            super().resolve(context) if subscription and subscription.is_active else {}
        )
        return {
            **result,
            "can_admin_collectivites": self._get_operator_admin_collectivites(
                context.get("account_email") or ""
            ),
        }

    @staticmethod
    def _get_operator_admin_collectivites(account_email):
        if not account_email:
            return []

        return list(
            models.Organization.objects.filter(
                type="commune",
                operator_roles__role="admin",
                operator_roles__operator__is_active=True,
                operator_roles__operator__user_roles__role="admin",
                operator_roles__operator__user_roles__user__email__iexact=account_email,
            )
            .exclude(Q(siren__isnull=True) | Q(siren=""))
            .order_by("siren")
            .values_list("siren", flat=True)
            .distinct()
        )
