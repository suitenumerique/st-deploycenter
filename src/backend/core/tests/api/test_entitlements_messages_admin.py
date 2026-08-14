# pylint: disable=too-many-lines
"""
Test can_admin_maildomains entitlement for Messages service.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.resolvers import get_admin_entitlement_resolver
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
    account.service_links.create(service=service, role="admin")

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
    account.service_links.create(service=other_service, role="admin")

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


def test_api_entitlements_messages_can_admin_maildomains_domain_scoped_service_admin():
    """Service admin with scope={"domains": ["d1.com"]} gets only scoped domains."""
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
        metadata={"domains": ["d1.com", "d2.com", "d3.com"]},
    )

    account = factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    account.service_links.create(
        service=service, role="admin", scope={"domains": ["d1.com"]}
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
                "can_admin_maildomains": ["d1.com"],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_unrestricted_service_admin():
    """Service admin with scope={} gets all subscription domains."""
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
        metadata={"domains": ["a.com", "b.com"]},
    )

    account = factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    account.service_links.create(service=service, role="admin", scope={})

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
    assert sorted(data["entitlements"]["can_admin_maildomains"]) == ["a.com", "b.com"]


def test_api_entitlements_messages_can_admin_maildomains_org_admin_ignores_scope():
    """Org-level admin always gets all domains regardless of any service link scope."""
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
        metadata={"domains": ["a.com", "b.com", "c.com"]},
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
    assert sorted(data["entitlements"]["can_admin_maildomains"]) == [
        "a.com",
        "b.com",
        "c.com",
    ]


def test_api_entitlements_messages_can_admin_maildomains_mixed_orgs_scoped():
    """Org admin in org A (all domains) + scoped service admin in org B."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    org_a = factories.OrganizationFactory(siret="12345678900001")
    org_b = factories.OrganizationFactory(siret="22345678900001")
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org_a)
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org_b)

    service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )
    factories.ServiceSubscriptionFactory(
        organization=org_a,
        service=service,
        operator=operator,
        metadata={"domains": ["org-a1.fr", "org-a2.fr"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=org_b,
        service=service,
        operator=operator,
        metadata={"domains": ["org-b1.fr", "org-b2.fr"]},
    )

    # Org-level admin in org A
    factories.AccountFactory(
        organization=org_a,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=["admin"],
    )

    # Scoped service admin in org B
    account_b = factories.AccountFactory(
        organization=org_b,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    account_b.service_links.create(
        service=service, role="admin", scope={"domains": ["org-b1.fr"]}
    )

    response = client.get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": org_a.siret,
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    data = response.json()
    domains = sorted(data["entitlements"]["can_admin_maildomains"])
    assert domains == ["org-a1.fr", "org-a2.fr", "org-b1.fr"]


def test_api_entitlements_messages_can_admin_maildomains_stale_scope_domains_discarded():
    """Scope domains not in subscription are discarded (intersection)."""
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
        metadata={"domains": ["a.fr", "b.fr"]},
    )

    account = factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    # scope has "removed.fr" which is no longer in subscription
    account.service_links.create(
        service=service,
        role="admin",
        scope={"domains": ["a.fr", "removed.fr"]},
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
                "can_admin_maildomains": ["a.fr"],
            },
        },
    )


def test_api_entitlements_messages_can_admin_maildomains_all_scope_domains_removed():
    """All scope domains removed from subscription → empty result for that org."""
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
        metadata={"domains": ["other.fr"]},
    )

    account = factories.AccountFactory(
        organization=organization,
        type="user",
        external_id="xyz",
        email="test@example.com",
        roles=[],
    )
    account.service_links.create(
        service=service,
        role="admin",
        scope={"domains": ["gone.fr"]},
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


# --- Operator admin passthrough tests ---


def _make_messages_service():
    """Helper: create a messages service with auth key."""
    return factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "test_token"},
    )


def _entitlements_request(client, service, siret, account_email=None, account_id=None):
    """Helper: call the entitlements endpoint."""
    params = {
        "service_id": service.id,
        "account_type": "user",
        "siret": siret,
    }
    if account_email:
        params["account_email"] = account_email
    if account_id:
        params["account_id"] = account_id
    return client.get(
        "/api/v1.0/entitlements/",
        query_params=params,
        headers={"X-Service-Auth": "Bearer test_token"},
    )


def test_operator_admin_passthrough_flag_on():
    """Operator admin gets all domains when flag is on the OperatorOrganizationRole."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr", "mairie.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    domains = response.json()["entitlements"]["can_admin_maildomains"]
    assert sorted(domains) == ["commune.fr", "mairie.fr"]


def test_operator_admin_passthrough_flag_off():
    """Operator admin gets nothing when flag is off (default)."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == []


def test_operator_admin_passthrough_wrong_operator():
    """User is admin of operator A, org role with flag belongs to operator B → no access."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator_a = factories.OperatorFactory()
    operator_b = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator_a)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator_b,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator_b,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == []


def test_operator_admin_passthrough_not_operator_admin():
    """User has no UserOperatorRole → no access even with flag on."""
    user = factories.UserFactory(email="random@user.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_email="random@user.fr"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == []


def test_operator_admin_passthrough_only_with_email():
    """Operator admin lookup requires account_email; account_id alone is not enough."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_id="some-external-id"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == []


def test_operator_admin_passthrough_inactive_subscription():
    """Inactive subscription for the queried org → no domains, but the field is
    still present (empty), since the Messages admin resolver is cross-org and
    always runs."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=False,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == []


def test_operator_admin_passthrough_multiple_orgs():
    """Operator admin gets domains from all orgs where flag is on."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    org_a = factories.OrganizationFactory(siret="12345678900001")
    org_b = factories.OrganizationFactory(siret="22345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=org_a, operator_admins_have_admin_role=True
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=org_b, operator_admins_have_admin_role=True
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=org_a,
        service=service,
        operator=operator,
        metadata={"domains": ["a.fr"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=org_b,
        service=service,
        operator=operator,
        metadata={"domains": ["b.fr"]},
    )

    response = _entitlements_request(
        client, service, org_a.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    domains = response.json()["entitlements"]["can_admin_maildomains"]
    assert sorted(domains) == ["a.fr", "b.fr"]


def test_operator_admin_passthrough_mixed_flags():
    """Only orgs with flag=true grant access."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    org_on = factories.OrganizationFactory(siret="12345678900001")
    org_off = factories.OrganizationFactory(siret="22345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=org_on, operator_admins_have_admin_role=True
    )
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org_off)

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=org_on,
        service=service,
        operator=operator,
        metadata={"domains": ["on.fr"]},
    )
    factories.ServiceSubscriptionFactory(
        organization=org_off,
        service=service,
        operator=operator,
        metadata={"domains": ["off.fr"]},
    )

    response = _entitlements_request(
        client, service, org_on.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == ["on.fr"]


def test_operator_admin_passthrough_requires_active_service_subscription():
    """Flag on OperatorOrganizationRole but no subscription for the queried
    service → no domains for that service (empty list)."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    queried_service = _make_messages_service()
    other_service = factories.ServiceFactory(
        type="messages",
        config={"entitlements_api_key": "other_token"},
    )

    # Subscription only for other_service, not queried_service
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=other_service,
        operator=operator,
        metadata={"domains": ["other.fr"]},
    )

    response = _entitlements_request(
        client, queried_service, organization.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    # The subscription is for another service, so no domains for this service —
    # but the field is present (empty) since the Messages resolver always runs.
    assert response.json()["entitlements"]["can_admin_maildomains"] == []


def test_operator_admin_passthrough_combined_with_account_admin():
    """Operator admin passthrough merges with regular account-level admin."""
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    org_a = factories.OrganizationFactory(siret="12345678900001")
    org_b = factories.OrganizationFactory(siret="22345678900001")
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org_a)
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=org_b, operator_admins_have_admin_role=True
    )

    service = _make_messages_service()

    # org_a: regular org-level admin
    factories.ServiceSubscriptionFactory(
        organization=org_a,
        service=service,
        operator=operator,
        metadata={"domains": ["a.fr"]},
    )
    factories.AccountFactory(
        organization=org_a,
        type="user",
        external_id="",
        email="admin@operator.fr",
        roles=["admin"],
    )

    # org_b: operator admin passthrough
    factories.ServiceSubscriptionFactory(
        organization=org_b,
        service=service,
        operator=operator,
        metadata={"domains": ["b.fr"]},
    )

    response = _entitlements_request(
        client, service, org_a.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    domains = response.json()["entitlements"]["can_admin_maildomains"]
    assert sorted(domains) == ["a.fr", "b.fr"]


def test_operator_admin_passthrough_email_must_match_exactly():
    """Email match is exact — different casing in User.email won't match.

    But when the entitlements request sends the account_email with the exact
    same casing as User.email, it matches and returns the admin domains.
    """
    user = factories.UserFactory(email="Admin@Operator.FR")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=organization,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, organization.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == []

    # But the exact same casing as User.email matches and returns the domains.
    response = _entitlements_request(
        client, service, organization.siret, account_email="Admin@Operator.FR"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == ["commune.fr"]


def test_operator_admin_passthrough_when_queried_org_has_no_subscription():
    """Regression (production SIDEC case): a user who is operator-admin of
    *other* organizations with active Messages must still receive
    can_admin_maildomains even when the organization actually being queried has
    no Messages subscription of its own.

    Before the fix, the admin resolver only ran when the queried org had its own
    active subscription, so this returned no can_admin_maildomains at all.
    """
    user = factories.UserFactory(email="admin@operator.fr")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    # The organization actually being queried (e.g. the operator's own org) has
    # NO Messages subscription.
    queried_org = factories.OrganizationFactory(siret="25390109400016")

    # A *different* organization the operator manages, with active Messages and
    # the admin passthrough flag on.
    managed_org = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=managed_org,
        operator_admins_have_admin_role=True,
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=managed_org,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
    )

    response = _entitlements_request(
        client, service, queried_org.siret, account_email="admin@operator.fr"
    )
    assert response.status_code == 200
    entitlements = response.json()["entitlements"]
    # The queried org itself is not activated...
    assert entitlements["can_access"] is False
    # ...but the cross-org admin domains are still surfaced.
    assert entitlements["can_admin_maildomains"] == ["commune.fr"]


def test_account_admin_domains_when_queried_org_has_no_subscription():
    """A service-admin in one organization gets that org's Messages domains even
    when the queried organization has no subscription of its own."""
    user = factories.UserFactory(email="admin@example.com")
    client = APIClient()
    client.force_login(user)

    operator = factories.OperatorFactory()

    # Queried org has no subscription at all.
    queried_org = factories.OrganizationFactory(siret="25390109400016")

    # Managed org has active Messages, and the user is a service-admin there.
    managed_org = factories.OrganizationFactory(siret="12345678900001")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=managed_org
    )

    service = _make_messages_service()
    factories.ServiceSubscriptionFactory(
        organization=managed_org,
        service=service,
        operator=operator,
        metadata={"domains": ["managed.fr"]},
    )
    account = factories.AccountFactory(
        organization=managed_org,
        type="user",
        external_id="",
        email="admin@example.com",
        roles=[],
    )
    account.service_links.create(service=service, role="admin")

    response = _entitlements_request(
        client, service, queried_org.siret, account_email="admin@example.com"
    )
    assert response.status_code == 200
    assert response.json()["entitlements"]["can_admin_maildomains"] == ["managed.fr"]


def test_non_messages_admin_resolver_not_run_without_active_subscription():
    """Scoping guard: for a non-Messages service, the admin resolver is NOT
    cross-org, so it must NOT run when the queried org has no active
    subscription. This proves the fix is scoped to Messages only and does not
    change behavior for other services (e.g. service_id pointing at adc/esd).
    """
    user = factories.UserFactory(email="contact@commune.fr")
    client = APIClient()
    client.force_login(user)

    # adc uses ExtendedAdminEntitlementResolver, which would return is_admin=True
    # via the population fallback (population < threshold) *if* it ran — so if
    # is_admin is absent, we know the resolver did not run.
    service = factories.ServiceFactory(
        type="adc",
        config={"entitlements_api_key": "test_token"},
    )

    organization = factories.OrganizationFactory(
        siret="12345678900001",
        population=100,  # under the auto-admin population threshold
    )
    # No subscription for this service → the queried org is not activated.

    response = _entitlements_request(
        client, service, organization.siret, account_email="contact@commune.fr"
    )
    assert response.status_code == 200
    entitlements = response.json()["entitlements"]
    assert entitlements["can_access"] is False
    # The (non-cross-org) admin resolver did not run: no admin fields leak in.
    assert "is_admin" not in entitlements
    assert "can_admin_maildomains" not in entitlements


def test_messages_admin_resolver_runs_without_active_subscription_flag():
    """The Messages admin resolver is flagged to run without an active
    subscription; the base and extended resolvers are not."""
    messages_service = factories.ServiceFactory(type="messages")
    adc_service = factories.ServiceFactory(type="adc")
    other_service = factories.ServiceFactory(type="some-other-type")

    assert (
        get_admin_entitlement_resolver(
            messages_service
        ).runs_without_active_subscription
        is True
    )
    assert (
        get_admin_entitlement_resolver(adc_service).runs_without_active_subscription
        is False
    )
    assert (
        get_admin_entitlement_resolver(other_service).runs_without_active_subscription
        is False
    )
