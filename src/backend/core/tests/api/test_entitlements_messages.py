# pylint: disable=invalid-name
"""
Test entitlements messages API endpoints in the deploycenter core app.
"""

import json
import threading
import responses
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import re
from rest_framework.test import APIClient

from core import factories, models
from core.entitlements.resolvers.access_entitlement_resolver import (
    AccessEntitlementResolver,
)
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db




@pytest.mark.django_db()
@responses.activate
def test_api_entitlements_list():
    """Test the entitlements list endpoint."""

    metrics_usage_endpoint = f"http://messages.suite.anct.gouv.fr/metrics/usage"

    responses.add(
        responses.GET,
        f"{metrics_usage_endpoint}?account_type=user&account_id=xyz&limit=1000&offset=0",
        json={
            "count": 1,
            "results": [
                {
                    "siret": "12345678900001",
                    "account": {
                        "type": "user",
                        "id": "xyz",
                    },
                    "metrics": {"storage_used": 500},
                }
            ],
        },
        status=200,
    )


    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": metrics_usage_endpoint,
            "metrics_auth_token": "test_token",
        },
    )
    service_subscription = factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        config={
            "max_storage": 1000,
        },
        account_type="user",
    )
    factories.EntitlementFactory(
        service_subscription=service_subscription,
        type=models.Entitlement.EntitlementType.MESSAGES_STORAGE,
        config={
            "max_storage": 5000,
        },
        account_type="organization",
    )

    # Test that we can upload to the drive
    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_store": True,
            },
        },
    )

    # Metrics should be stored in the database
    metrics = models.Metric.objects.filter(service=service, organization=organization)
    assert metrics.count() == 1
    assert metrics.first().value == 500
    assert metrics.first().key == "storage_used"
    assert metrics.first().account_type == "user"
    assert metrics.first().account_id == "xyz"
    assert metrics.first().organization == organization
