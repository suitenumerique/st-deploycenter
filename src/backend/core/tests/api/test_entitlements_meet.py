# pylint: disable=invalid-name
"""
Test entitlements meet API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.resolvers.meet_access_entitlement_resolver import (
    MeetAccessEntitlementResolver,
)

pytestmark = pytest.mark.django_db


def test_api_entitlements_meet_can_create_with_active_subscription():
    """
    Test that the meet service returns can_create: true when the subscription is active.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="meet",
        config={
            "entitlements_api_key": "test_token",
        },
    )

    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator
    )

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
    assert data == {
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_create": True,
        },
    }


def test_api_entitlements_meet_can_create_without_subscription():
    """
    Test that the meet service returns can_create: false when there is no subscription.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="meet",
        config={
            "entitlements_api_key": "test_token",
        },
    )

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
    assert data == {
        "operator": None,
        "entitlements": {
            "can_create": False,
            "can_create_reason": MeetAccessEntitlementResolver.Reason.NOT_ACTIVATED,
        },
    }


def test_api_entitlements_meet_can_create_with_inactive_subscription():
    """
    Test that the meet service returns can_create: false when the subscription is inactive.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="meet",
        config={
            "entitlements_api_key": "test_token",
        },
    )

    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator, is_active=False
    )

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
    assert data == {
        "operator": None,
        "entitlements": {
            "can_create": False,
            "can_create_reason": MeetAccessEntitlementResolver.Reason.NOT_ACTIVATED,
        },
    }


def test_api_entitlements_meet_can_create_no_organization():
    """
    Test that the meet service returns can_create: false when the organization is not found.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    service = factories.ServiceFactory(
        type="meet",
        config={
            "entitlements_api_key": "test_token",
        },
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": "99999999999999",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "operator": None,
        "entitlements": {
            "can_create": False,
            "can_create_reason": MeetAccessEntitlementResolver.Reason.NO_ORGANIZATION,
        },
    }
