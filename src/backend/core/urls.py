"""
URL configuration for core app.
"""
# pylint: disable=line-too-long

from django.conf import settings
from django.urls import include, path, re_path

from rest_framework.routers import DefaultRouter, SimpleRouter

from core.api.viewsets.accounts import AccountViewSet, OrganizationAccountsViewSet
from core.authentication.urls import urlpatterns as oidc_urls

from .api.viewsets.config import ConfigView
from .api.viewsets.entitlements import EntitlementView
from .api.viewsets.lagaufre import LagaufreViewSet
from .api.viewsets.operator import OperatorViewSet
from .api.viewsets.organization import OperatorOrganizationViewSet
from .api.viewsets.service import (
    OrganizationServiceSubscriptionEntitlementViewSet,
    OrganizationServiceSubscriptionViewSet,
    OrganizationServiceViewSet,
    ServiceLogoViewSet,
    SubscriptionEntitlementViewSet,
)
from .api.viewsets.metrics import OperatorMetricsViewSet
from .api.viewsets.user import UserViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r"lagaufre", LagaufreViewSet, basename="lagaufre")
router.register(r"servicelogo", ServiceLogoViewSet, basename="servicelogo")
router.register(r"users", UserViewSet, basename="user")
router.register(r"operators", OperatorViewSet)

operator_organization_router = DefaultRouter()
operator_organization_router.register(r"organizations", OperatorOrganizationViewSet)

organization_service_router = DefaultRouter()
organization_service_router.register(r"services", OrganizationServiceViewSet)

account_router = DefaultRouter()
account_router.register(r"accounts", AccountViewSet)

organization_accounts_router = DefaultRouter()
organization_accounts_router.register(r"accounts", OrganizationAccountsViewSet)


organization_subscription_entitlements_router = DefaultRouter()
organization_subscription_entitlements_router.register(
    r"", OrganizationServiceSubscriptionEntitlementViewSet
)

subscription_entitlements_router = SimpleRouter()
subscription_entitlements_router.register(r"", SubscriptionEntitlementViewSet)


urlpatterns = [
    # Include all router URLs
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                path(
                    "entitlements/",
                    include(
                        [
                            path(
                                "", EntitlementView.as_view(), name="api-entitlements"
                            ),
                            *subscription_entitlements_router.urls,
                        ]
                    ),
                ),
                *account_router.urls,
                path("config/", ConfigView.as_view(), name="api-config"),
                re_path(
                    r"^operators/(?P<operator_id>[0-9a-z-]*)/",
                    include(
                        [
                            *operator_organization_router.urls,
                            path(
                                "metrics/",
                                OperatorMetricsViewSet.as_view({"get": "list"}),
                                name="operator-metrics",
                            ),
                            re_path(
                                r"^organizations/(?P<organization_id>[0-9a-z-]*)/",
                                include(
                                    [
                                        *organization_service_router.urls,
                                        *organization_accounts_router.urls,
                                        re_path(
                                            r"^services/(?P<service_id>[0-9a-z-]*)/",
                                            include(
                                                [
                                                    path(
                                                        "subscription/",
                                                        include(
                                                            [
                                                                path(
                                                                    "",
                                                                    OrganizationServiceSubscriptionViewSet.as_view(
                                                                        {
                                                                            "get": "retrieve",
                                                                            "patch": "partial_update",
                                                                            "delete": "destroy",
                                                                        }
                                                                    ),
                                                                    name="organizationservice-subscription",
                                                                ),
                                                                path(
                                                                    "entitlements/",
                                                                    include(
                                                                        organization_subscription_entitlements_router.urls
                                                                    ),
                                                                ),
                                                            ]
                                                        ),
                                                    ),
                                                ]
                                            ),
                                        ),
                                    ]
                                ),
                            ),
                        ]
                    ),
                ),
            ]
        ),
    ),
]
