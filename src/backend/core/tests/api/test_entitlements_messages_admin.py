"""
Test can_admin_maildomains entitlement for Messages service.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db


def test_api_entitlements_messages_can_admin_maildomains_org_admin():
    """User with org-level admin role gets domains from subscription metadata."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["domain1.com", "domain2.com"]},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=["admin"],
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
    assert_equals_partial(
        data,
        {
            "entitlements": {
                "can_access": True,
                "can_admin_maildomains": ["domain1.com", "domain2.com"],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_service_admin():
    """User with service-level admin role gets domains from subscription metadata."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["service-domain.com"]},
    )

    account = factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    account.service_links.create(service=service, roles=["admin"])

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
            "entitlements": {
                "can_access": True,
                "can_admin_maildomains": ["service-domain.com"],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_admin_on_other_service():
    """User with admin role on another service should NOT get domains for the messages service."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    messages_service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    other_service = factories.ServiceFactory(type="other")

    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=messages_service,
        operator=operator,
        metadata={"domains": ["domain1.com"]},
    )

    # User has admin on the other service, not on messages
    account = factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    account.service_links.create(service=other_service, roles=["admin"])

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": messages_service.id,
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
            "entitlements": {
                "can_access": True,
                "can_admin_maildomains": [],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_not_admin():
    """User without admin role gets empty can_admin_maildomains."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["domain1.com"]},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
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
    assert_equals_partial(
        data,
        {
            "entitlements": {
                "can_access": True,
                "can_admin_maildomains": [],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_multiple_orgs():
    """User admin in multiple orgs gets domains from all their subscriptions."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()

    org1 = factories.OrganizationFactory(siret="12345678900001")
    org2 = factories.OrganizationFactory(siret="22345678900001")
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org1)
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org2)

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=org1,
        service=service,
        operator=operator,
        metadata={"domains": ["org1-domain.com"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=org2,
        service=service,
        operator=operator,
        metadata={"domains": ["org2-domain.com", "org2-other.com"]},
    )

    factories.AccountFactory(
        organization=org1,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=["admin"],
    )
    factories.AccountFactory(
        organization=org2,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=["admin"],
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": org1.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    domains = data["entitlements"]["can_admin_maildomains"]
    assert sorted(domains) == ["org1-domain.com", "org2-domain.com", "org2-other.com"]


def test_api_entitlements_messages_can_admin_maildomains_no_domains_metadata():
    """Admin user with subscription that has no domains in metadata gets empty list."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=["admin"],
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
    assert_equals_partial(
        data,
        {
            "entitlements": {
                "can_access": True,
                "can_admin_maildomains": [],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_by_email():
    """can_admin_maildomains works when looking up user by email."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["email-domain.com"]},
    )

    factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=["admin"],
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_email": "test@example.com",
            "siret": organization.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert_equals_partial(
        data,
        {
            "entitlements": {
                "can_access": True,
                "can_admin_maildomains": ["email-domain.com"],
            },
        },
    )
