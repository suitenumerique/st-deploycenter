"""
URL configuration for core app.
"""

from django.conf import settings
from django.urls import include, path

from rest_framework.routers import DefaultRouter

from core.authentication.urls import urlpatterns as oidc_urls

from .api.viewsets.config import ConfigView
from .api.viewsets.lagaufre import LagaufreViewSet
from .api.viewsets.service import ServiceLogoViewSet, ServiceViewSet
from .api.viewsets.user import UserViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r"lagaufre", LagaufreViewSet, basename="lagaufre")
router.register(r"services", ServiceViewSet)
router.register(r"servicelogo", ServiceLogoViewSet, basename="servicelogo")
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    # Include all router URLs
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                path("config/", ConfigView.as_view(), name="api-config"),
            ]
        ),
    ),
]
