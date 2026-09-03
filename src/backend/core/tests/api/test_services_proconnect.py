"""
Test ProConnect services API endpoints in the deploycenter core app.
"""

import re

from django.db import connection
from django.test.utils import CaptureQueriesContext

import pytest
from rest_framework.test import APIClient

from core import factories
from core.services.locks import advisory_lock_key

pytestmark = pytest.mark.django_db


def test_api_organization_proconnect_service_cannot_activate_if_mail_domain_is_not_set():
    """Test that it is not possible to activate a ProConnect service if the mail domain is not set."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "1234567890"}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the service cannot be activated by default
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is True

    # Check that the subscription cannot be created if the mail domain is not set
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {
        "metadata": ["Mail domain is required for ProConnect subscription."]
    }


def test_api_organization_proconnect_service_cannot_activate_if_idp_is_not_set():
    """Test that it is not possible to activate a ProConnect service if the IDP is not set on the service config."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    # Service without idp_id in config
    service = factories.ServiceFactory(type="proconnect")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the service cannot be activated by default
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is True

    # Check that the subscription cannot be created if the IDP is not set
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {
        "__all__": ["IDP is required for ProConnect subscription."]
    }


def test_api_organization_proconnect_service_can_activate_if_mail_domain_and_idp_are_set():
    """Test that it is possible to activate a ProConnect service if the mail domain and IDP are set."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "1234567890"}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the service can be activated by default
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is True

    # Check that the subscription can be created if the mail domain and IDP are set
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 201


def test_api_organization_proconnect_service_can_update_subscription_to_set_inactive():
    """Test that it is possible to create an inactive ProConnect subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "1234567890"}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the subscription can be created inactive
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 201


def test_api_organization_proconnect_create_validates_mail_domain():
    """Test that creating a ProConnect subscription without mail domain fails at serializer level."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    # Organization without mail domain
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "1234567890"}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Create (no existing subscription) with is_active=True — should fail
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert "Mail domain is required" in str(response.json())


def test_api_organization_proconnect_create_builds_metadata():
    """Test that creating a ProConnect subscription correctly builds metadata (domains only, no idp_id)."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Create (no existing subscription) with valid domain
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 201
    data = response.json()
    # idp_id should NOT be in metadata anymore
    assert "idp_id" not in data["metadata"]
    assert data["metadata"]["domains"] == ["commune.fr"]


def test_api_organization_proconnect_service_config_exposes_idp_id():
    """Test that the service config exposes idp_id to the frontend."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(
        type="proconnect",
        config={"idp_id": "my-idp", "secret_key": "should-not-appear"},
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["config"]["idp_id"] == "my-idp"
    assert "secret_key" not in data["config"]


def test_api_organization_proconnect_superuser_can_override_domains():
    """Test that a superuser can override domains on an org with RPNT mail_domain."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "domains": ["custom.fr", "other.fr"],
            },
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.json()
    assert data["metadata"]["domains"] == ["custom.fr", "other.fr"]
    assert "idp_id" not in data["metadata"]


def test_api_organization_proconnect_regular_user_cannot_route_a_domain_the_org_lacks():
    """A regular user's routing is bounded by proconnect_routable — and refused, not ignored.

    It used to force the list silently back to the RPNT domain and answer 201, so
    the caller got a success carrying domains it never sent.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "domains": ["custom.fr", "other.fr"],
            },
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "not routable" in str(response.json())


def test_api_organization_proconnect_regular_user_can_route_a_routable_domain():
    """A regular user routes a domain the organization holds — no superuser needed."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
        # Validated by a superuser earlier: routable, so offered in the modal.
        proconnect_domains={"manual": ["autre.fr"]},
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/",
        {"metadata": {"domains": ["autre.fr"]}, "is_active": False},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["domains"] == ["autre.fr"]


def test_api_organization_proconnect_superuser_can_set_domains_without_rpnt():
    """Test that a superuser can set domains on an org without mail_domain."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    # Organization without RPNT / mail_domain
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "domains": ["custom.fr"],
            },
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.json()
    assert data["metadata"]["domains"] == ["custom.fr"]


def test_api_organization_proconnect_regular_user_cannot_set_domains_without_rpnt():
    """A regular user on an org with nothing routable is refused whatever it sends."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "domains": ["custom.fr"],
            },
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 400
    # Refused for not being routable, before the "needs a domain to activate" check.
    assert "not routable" in str(response.json())


def test_api_organization_proconnect_superuser_can_update_existing_domains():
    """Test that a superuser can update domains on an existing subscription."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Create an active subscription first
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
        is_active=True,
    )

    # Superuser updates domains
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "domains": ["new-domain.fr", "another.fr"],
            },
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["domains"] == ["another.fr", "new-domain.fr"]


def test_api_organization_proconnect_superuser_empty_domains_blocks_activation():
    """Test that a superuser sending empty domains with is_active=true gets 400."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "domains": [],
            },
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "Mail domain is required" in str(response.json())


# --- Domain uniqueness tests ---


def test_api_organization_proconnect_domain_uniqueness_blocks_overlapping_domains():
    """Test that activating a second ProConnect subscription with overlapping domains fails
    even within the same organization."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service1 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp1"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service1)
    service2 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp2"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service2)

    # Create first active subscription with domain
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service1,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
        is_active=True,
    )

    # Try to create second subscription with overlapping domain
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service2.id}/subscription/",
        {
            "metadata": {"domains": ["commune.fr", "other.fr"]},
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "commune.fr" in str(response.json())
    assert "already used" in str(response.json())


def test_api_organization_proconnect_domain_uniqueness_locks_each_domain():
    """The uniqueness check locks the domains themselves.

    select_for_update can only lock rows that already exist, so two transactions
    activating the same domain on different subscriptions would both find no
    conflict. The advisory lock makes the second one wait and then see the first.
    """
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp1"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/"
    )
    with CaptureQueriesContext(connection) as ctx:
        response = client.patch(
            url,
            {"metadata": {"domains": ["b.fr", "a.fr"]}, "is_active": True},
            format="json",
        )
    assert response.status_code == 201

    locks = [
        q["sql"] for q in ctx.captured_queries if "pg_advisory_xact_lock" in q["sql"]
    ]
    # One per domain, taken in sorted order so two writers can't deadlock.
    # (No idp lock here: api-partenaires is unconfigured, so no push runs.)
    keys = [int(re.search(r"\(\s*(-?\d+)\)", sql).group(1)) for sql in locks]
    assert keys == [
        advisory_lock_key("domain", "a.fr"),
        advisory_lock_key("domain", "b.fr"),
    ]


def test_api_organization_proconnect_domain_uniqueness_blocks_across_organizations():
    """Test that domain uniqueness is global: a domain used by org A blocks org B."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    org_a = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org_a)

    org_b = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(operator=operator, organization=org_b)

    service1 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp1"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service1)
    service2 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp2"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service2)

    # Org A owns "commune.fr"
    factories.ServiceSubscriptionFactory(
        organization=org_a,
        service=service1,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
        is_active=True,
    )

    # Org B tries to use the same domain — should fail
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{org_b.id}/services/{service2.id}/subscription/",
        {
            "metadata": {"domains": ["commune.fr"]},
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "commune.fr" in str(response.json())
    assert "already used" in str(response.json())


def test_api_organization_proconnect_domain_uniqueness_allows_disjoint_domains():
    """Test that activating a second ProConnect subscription with disjoint domains succeeds."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service1 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp1"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service1)
    service2 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp2"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service2)

    # Create first active subscription with domain
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service1,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
        is_active=True,
    )

    # Create second subscription with different domain — should succeed
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service2.id}/subscription/",
        {
            "metadata": {"domains": ["other.fr"]},
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.json()
    assert data["metadata"]["domains"] == ["other.fr"]


def test_api_organization_proconnect_domain_uniqueness_ignores_inactive_subscriptions():
    """Test that inactive ProConnect subscriptions don't block domain reuse."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service1 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp1"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service1)
    service2 = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp2"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service2)

    # Create first INACTIVE subscription with domain
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service1,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
        is_active=False,
    )

    # Create second active subscription with same domain — should succeed
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service2.id}/subscription/",
        {
            "metadata": {"domains": ["commune.fr"]},
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.json()
    assert data["metadata"]["domains"] == ["commune.fr"]


def test_api_organization_proconnect_domain_uniqueness_allows_same_sub_update():
    """Test that updating the same subscription's domains doesn't trigger uniqueness error."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "idp1"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Create active subscription with domain
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"domains": ["commune.fr"]},
        is_active=True,
    )

    # Update same subscription with same domain — should succeed
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {"domains": ["commune.fr", "extra.fr"]},
        },
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["domains"] == ["commune.fr", "extra.fr"]


@pytest.mark.parametrize("service_type", ["proconnect", "domains", "drive"])
@pytest.mark.parametrize("metadata", ["a string", 42, ["a.fr"], True])
def test_api_subscription_rejects_a_non_object_metadata(service_type, metadata):
    """A metadata that is not an object is a 400, never a 500.

    DRF's JSONField takes any JSON value, and each per-service validator reads
    metadata with .get()/in — so a scalar or a list used to raise
    AttributeError/TypeError out of validate(), i.e. a 500 on caller-controlled
    input. Covers the three validators, which each failed differently.
    """
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type=service_type, config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/",
        {"metadata": metadata, "is_active": False},
        format="json",
    )
    assert response.status_code == 400
    assert "metadata" in response.json()


def test_api_subscription_rejects_a_non_object_body():
    """A list body is a 400: to_internal_value's `{**data}` used to TypeError."""
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="drive")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/",
        [{"is_active": True}],
        format="json",
    )
    assert response.status_code == 400


def test_api_subscription_rejects_the_entitlements_input_field_name():
    """`entitlements_input` must not reach ModelSerializer.update().

    It is the declared write field (source="entitlements"); clients send
    "entitlements". Only the latter used to be popped, so the former reached
    super() as a writable nested field and tripped DRF's assertion — a 500.
    """
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="drive")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/"
    )
    assert client.patch(url, {"is_active": True}, format="json").status_code == 201

    response = client.patch(
        url, {"entitlements_input": [], "is_active": True}, format="json"
    )
    assert response.status_code != 500


@pytest.mark.parametrize("domains", ["notalist", 42, [1, 2], [{"a": 1}], [None]])
def test_api_organization_proconnect_rejects_a_malformed_domains_value(domains):
    """A domains value that is not a list of strings is a 400, not a silent drop.

    It used to fall through to the "not submitted" branch (or be filtered out by
    normalization), so the caller got a 200 carrying domains it never sent.
    """
    user = factories.UserFactory(is_superuser=True)
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect", config={"idp_id": "abc123"})
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/",
        {"metadata": {"domains": domains}, "is_active": False},
        format="json",
    )
    assert response.status_code == 400
    assert "metadata" in response.json()
