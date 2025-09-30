"""
URL configuration for core app.
"""

from django.conf import settings
from django.urls import include, path, re_path

from rest_framework.routers import DefaultRouter

from core.authentication.urls import urlpatterns as oidc_urls

from .api.viewsets.config import ConfigView
from .api.viewsets.operator import OperatorViewSet
from .api.viewsets.service import ServiceLogoViewSet, ServiceViewSet
from .api.viewsets.user import UserViewSet
from .api.viewsets.organization import OperatorOrganizationViewSet
from .api.viewsets.organization import OrganizationViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r"services", ServiceViewSet)
router.register(r"servicelogo", ServiceLogoViewSet, basename="servicelogo")
router.register(r"users", UserViewSet, basename="user")
router.register(r"operators", OperatorViewSet)
router.register(r"organizations", OrganizationViewSet)

operator_organization_router = DefaultRouter()
operator_organization_router.register(r"organizations", OperatorOrganizationViewSet)

urlpatterns = [
    # Include all router URLs
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                path("config/", ConfigView.as_view(), name="api-config"),
                re_path(r"^operators/(?P<resource_id>[0-9a-z-]*)/", include(operator_organization_router.urls)),

            ]
        ),
    ),
]
