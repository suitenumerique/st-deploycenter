# pylint: disable=invalid-name
"""
Test entitlements transfers API endpoints in the deploycenter core app.

The transfers service does not have its own subscription model: an organization
can access it iff it has an active subscription to a Drive service.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.resolvers.transfers_access_entitlement_resolver import (
    TransfersAccessEntitlementResolver,
)

pytestmark = pytest.mark.django_db


def _make_transfers_service():
    return factories.ServiceFactory(
        type="transfers",
        config={
            "entitlements_api_key": "test_token",
        },
    )


def _call_entitlements(client, service, siret):
    return client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )


def test_api_entitlements_transfers_can_access_with_active_drive_subscription():
    """
    Transfers grants access when the organization has an active drive subscription.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    drive_service = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=organization, service=drive_service, operator=operator
    )

    transfers_service = _make_transfers_service()

    response = _call_entitlements(client, transfers_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": {
            "id": str(organization.id),
            "type": organization.type,
            "name": organization.name,
            "oidc_valid": None,
        },
        "operator": None,
        "potentialOperators": [],
        "entitlements": {
            "can_access": True,
        },
    }


def test_api_entitlements_transfers_can_access_without_drive_subscription():
    """
    Transfers denies access when the organization has no drive subscription at all.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    transfers_service = _make_transfers_service()

    response = _call_entitlements(client, transfers_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": {
            "id": str(organization.id),
            "type": organization.type,
            "name": organization.name,
            "oidc_valid": None,
        },
        "operator": None,
        "potentialOperators": [],
        "entitlements": {
            "can_access": False,
            "can_access_reason": TransfersAccessEntitlementResolver.Reason.NOT_ACTIVATED,
        },
    }


def test_api_entitlements_transfers_can_access_with_inactive_drive_subscription():
    """
    Transfers denies access when the drive subscription exists but is inactive.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    drive_service = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=drive_service,
        operator=operator,
        is_active=False,
    )

    transfers_service = _make_transfers_service()

    response = _call_entitlements(client, transfers_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"] == {
        "can_access": False,
        "can_access_reason": TransfersAccessEntitlementResolver.Reason.NOT_ACTIVATED,
    }


def test_api_entitlements_transfers_can_access_no_organization():
    """
    Transfers denies access with NO_ORGANIZATION when the siret matches no org.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    transfers_service = _make_transfers_service()

    response = _call_entitlements(client, transfers_service, "99999999999999")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": None,
        "operator": None,
        "entitlements": {
            "can_access": False,
            "can_access_reason": TransfersAccessEntitlementResolver.Reason.NO_ORGANIZATION,
        },
    }


def test_api_entitlements_transfers_ignores_transfers_subscription():
    """
    A transfers-only subscription must not grant access — the gating depends on
    drive, not on transfers' own subscription.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    transfers_service = _make_transfers_service()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=transfers_service, operator=operator
    )

    response = _call_entitlements(client, transfers_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"]["can_access"] is False
    assert (
        data["entitlements"]["can_access_reason"]
        == TransfersAccessEntitlementResolver.Reason.NOT_ACTIVATED
    )


def test_api_entitlements_transfers_ignores_other_org_drive_subscription():
    """
    A drive subscription belonging to a different organization must not leak access.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    other_organization = factories.OrganizationFactory(siret="98765432100001")
    drive_service = factories.ServiceFactory(type="drive")
    factories.ServiceSubscriptionFactory(
        organization=other_organization, service=drive_service, operator=operator
    )

    transfers_service = _make_transfers_service()

    response = _call_entitlements(client, transfers_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"] == {
        "can_access": False,
        "can_access_reason": TransfersAccessEntitlementResolver.Reason.NOT_ACTIVATED,
    }
