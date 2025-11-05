"""
URL configuration for core app.
"""

from django.conf import settings
from django.urls import include, path, re_path

from rest_framework.routers import DefaultRouter

from core.authentication.urls import urlpatterns as oidc_urls

from .api.viewsets.config import ConfigView
from .api.viewsets.entitlements import EntitlementView
from .api.viewsets.lagaufre import LagaufreViewSet
from .api.viewsets.operator import OperatorViewSet
from .api.viewsets.organization import OperatorOrganizationViewSet
from .api.viewsets.service import (
    OrganizationServiceSubscriptionViewSet,
    OrganizationServiceViewSet,
    ServiceLogoViewSet,
    ServiceViewSet,
)
from .api.viewsets.user import UserViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r"lagaufre", LagaufreViewSet, basename="lagaufre")
router.register(r"services", ServiceViewSet)
router.register(r"servicelogo", ServiceLogoViewSet, basename="servicelogo")
router.register(r"users", UserViewSet, basename="user")
router.register(r"operators", OperatorViewSet)

operator_organization_router = DefaultRouter()
operator_organization_router.register(r"organizations", OperatorOrganizationViewSet)

organization_service_router = DefaultRouter()
organization_service_router.register(r"services", OrganizationServiceViewSet)

organization_service_subscription_router = DefaultRouter()
organization_service_subscription_router.register(
    r"subscription", OrganizationServiceSubscriptionViewSet
)

urlpatterns = [
    # Include all router URLs
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                path(
                    "entitlements/", EntitlementView.as_view(), name="api-entitlements"
                ),
                path("config/", ConfigView.as_view(), name="api-config"),
                re_path(
                    r"^operators/(?P<operator_id>[0-9a-z-]*)/",
                    include(
                        [
                            *operator_organization_router.urls,
                            re_path(
                                r"^organizations/(?P<organization_id>[0-9a-z-]*)/",
                                include(
                                    [
                                        *organization_service_router.urls,
                                        re_path(
                                            r"^services/(?P<service_id>[0-9a-z-]*)/",
                                            include(
                                                organization_service_subscription_router.urls
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
