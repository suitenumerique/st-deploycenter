# pylint: disable=invalid-name
"""
Test entitlements calendars API endpoints in the deploycenter core app.

The calendars service does not have its own subscription model: an organization
can access it iff it has an active subscription to a Messages service.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.resolvers.calendars_access_entitlement_resolver import (
    CalendarsAccessEntitlementResolver,
)

pytestmark = pytest.mark.django_db


def _make_calendars_service():
    return factories.ServiceFactory(
        type="calendars",
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


def test_api_entitlements_calendars_can_access_with_active_messages_subscription():
    """
    Calendars grants access when the organization has an active messages subscription.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    messages_service = factories.ServiceFactory(type="messages")
    factories.ServiceSubscriptionFactory(
        organization=organization, service=messages_service, operator=operator
    )

    calendars_service = _make_calendars_service()

    response = _call_entitlements(client, calendars_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": {
            "id": str(organization.id),
            "type": organization.type,
            "name": organization.name,
            "oidc_valid": None,
        },
        "operator": {
            "id": str(operator.id),
            "name": operator.name,
            "siret": operator.siret,
            "url": operator.url,
            "config": {},
        },
        "entitlements": {
            "can_access": True,
        },
    }


def test_api_entitlements_calendars_can_access_without_messages_subscription():
    """
    Calendars denies access when the organization has no messages subscription at all.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    calendars_service = _make_calendars_service()

    response = _call_entitlements(client, calendars_service, organization.siret)

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
            "can_access_reason": CalendarsAccessEntitlementResolver.Reason.NOT_ACTIVATED,
        },
    }


def test_api_entitlements_calendars_can_access_with_inactive_messages_subscription():
    """
    Calendars denies access when the messages subscription exists but is inactive.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    messages_service = factories.ServiceFactory(type="messages")
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=messages_service,
        operator=operator,
        is_active=False,
    )

    calendars_service = _make_calendars_service()

    response = _call_entitlements(client, calendars_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"] == {
        "can_access": False,
        "can_access_reason": CalendarsAccessEntitlementResolver.Reason.NOT_ACTIVATED,
    }


def test_api_entitlements_calendars_can_access_no_organization():
    """
    Calendars denies access with NO_ORGANIZATION when the siret matches no org.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    calendars_service = _make_calendars_service()

    response = _call_entitlements(client, calendars_service, "99999999999999")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "organization": None,
        "operator": None,
        "entitlements": {
            "can_access": False,
            "can_access_reason": CalendarsAccessEntitlementResolver.Reason.NO_ORGANIZATION,
        },
    }


def test_api_entitlements_calendars_ignores_calendars_subscription():
    """
    A calendars-only subscription must not grant access — the gating depends on
    messages, not on calendars' own subscription.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    calendars_service = _make_calendars_service()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=calendars_service, operator=operator
    )

    response = _call_entitlements(client, calendars_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"]["can_access"] is False
    assert (
        data["entitlements"]["can_access_reason"]
        == CalendarsAccessEntitlementResolver.Reason.NOT_ACTIVATED
    )


def test_api_entitlements_calendars_ignores_other_org_messages_subscription():
    """
    A messages subscription belonging to a different organization must not leak access.
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
    messages_service = factories.ServiceFactory(type="messages")
    factories.ServiceSubscriptionFactory(
        organization=other_organization, service=messages_service, operator=operator
    )

    calendars_service = _make_calendars_service()

    response = _call_entitlements(client, calendars_service, organization.siret)

    assert response.status_code == 200
    data = response.json()
    assert data["entitlements"] == {
        "can_access": False,
        "can_access_reason": CalendarsAccessEntitlementResolver.Reason.NOT_ACTIVATED,
    }
