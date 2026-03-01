"""
Test users API endpoints in the deploycenter core app.
"""

# pylint: disable=too-many-lines

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


def test_api_organizations_services_list_anonymous():
    """Anonymous users should not be allowed to retrieve organization services."""
    factories.UserFactory.create_batch(2)
    client = APIClient()

    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 401


def test_api_organizations_services_list_authenticated():
    """
    Authenticated users should be able to retrieve organization services of an operator
    for which they have a UserOperatorRole.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory(name="C")
    organization_nok2 = factories.OrganizationFactory(name="D")
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    service3 = factories.ServiceFactory()
    service4 = factories.ServiceFactory()

    # Create OperatorServiceConfig for some services
    config1 = factories.OperatorServiceConfigFactory(
        operator=operator, service=service1, display_priority=10
    )
    config2 = factories.OperatorServiceConfigFactory(
        operator=operator, service=service2, display_priority=5
    )
    config4 = factories.OperatorServiceConfigFactory(
        operator=operator, service=service4, display_priority=15
    )
    # service3 has no config - should still appear if it has a subscription
    # service4 has config but no subscription - should appear

    factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )
    factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service2, operator=operator
    )
    factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service3, operator=operator
    )
    # service4 has config but no subscription - should still appear
    # This subscription is for a different operator, so service2 won't appear for operator
    factories.ServiceSubscriptionFactory(
        organization=organization_nok1, service=service2, operator=operator2
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/"
    )
    assert response.status_code == 200
    content = response.json()
    results = content["results"]
    assert len(results) == 4

    # Results are ordered by service id - find each service in results
    results_by_id = {result["id"]: result for result in results}

    # Check service1 (has subscription and config)
    service1_result = results_by_id[service1.id]
    assert service1_result["name"] == service1.name
    assert service1_result["subscription"] is not None
    assert "is_active" in service1_result["subscription"]
    assert (
        service1_result["operator_config"]["display_priority"]
        == config1.display_priority
    )
    assert (
        service1_result["operator_config"]["externally_managed"]
        == config1.externally_managed
    )

    # Check service2 (has subscription and config)
    service2_result = results_by_id[service2.id]
    assert service2_result["name"] == service2.name
    assert service2_result["subscription"] is not None
    assert "is_active" in service2_result["subscription"]
    assert (
        service2_result["operator_config"]["display_priority"]
        == config2.display_priority
    )
    assert (
        service2_result["operator_config"]["externally_managed"]
        == config2.externally_managed
    )

    # Check service3 (has subscription, no config)
    service3_result = results_by_id[service3.id]
    assert service3_result["name"] == service3.name
    assert service3_result["subscription"] is not None
    assert "is_active" in service3_result["subscription"]
    assert service3_result["operator_config"] is None

    # Check service4 (has config, no subscription)
    service4_result = results_by_id[service4.id]
    assert service4_result["name"] == service4.name
    assert service4_result["subscription"] is None
    assert (
        service4_result["operator_config"]["display_priority"]
        == config4.display_priority
    )
    assert (
        service4_result["operator_config"]["externally_managed"]
        == config4.externally_managed
    )

    # Test the list of organizations with services
    response = client.get(f"/api/v1.0/operators/{operator.id}/organizations/")
    content = response.json()
    results = content["results"]
    assert len(results) == 2

    # Find organizations by id
    results_by_id = {result["id"]: result for result in results}

    # Check organization_ok1 has 3 service subscriptions
    org1_result = results_by_id[str(organization_ok1.id)]
    assert org1_result["name"] == organization_ok1.name
    assert len(org1_result["service_subscriptions"]) == 3

    # Verify all three subscriptions are present
    subscription_service_ids = {
        sub["service"]["id"] for sub in org1_result["service_subscriptions"]
    }
    assert service1.id in subscription_service_ids
    assert service2.id in subscription_service_ids
    assert service3.id in subscription_service_ids

    assert org1_result["service_subscriptions"][0]["is_active"] is True
    assert org1_result["service_subscriptions"][1]["is_active"] is True
    assert org1_result["service_subscriptions"][2]["is_active"] is True

    # Check organization_ok2 has no service subscriptions
    org2_result = results_by_id[str(organization_ok2.id)]
    assert org2_result["name"] == organization_ok2.name
    assert len(org2_result["service_subscriptions"]) == 0

    # Check that we don't have access to the organization via operator2
    response = client.get(f"/api/v1.0/operators/{operator2.id}/organizations/")
    assert response.status_code == 403

    response = client.get(
        f"/api/v1.0/operators/{operator2.id}/organizations/{organization_ok1.id}/services/"
    )
    assert response.status_code == 403


def test_api_organization_service_enable_delete():
    """Authenticated users should be able to enable and delete a service subscription for an organization."""
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_nok1, service=service2, operator=operator2
    )

    # Test that no subscription exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/"
    )
    assert response.status_code == 404

    # Test that the subscription can be created
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 201
    content_created = response.json()
    assert "metadata" in content_created
    assert "created_at" in content_created

    # Test that the subscription exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/"
    )
    assert response.status_code == 200
    content_retrieved = response.json()
    assert content_retrieved["metadata"] == content_created["metadata"]
    assert content_retrieved["created_at"] == content_created["created_at"]
    assert content_retrieved["is_active"] == content_created["is_active"]

    # Test that the subscription can be deleted
    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/"
    )
    response = client.delete(url)
    assert response.status_code == 204

    # Test that the subscription does not exist
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/"
    )
    assert response.status_code == 404


def test_api_organization_service_inactive():
    """Authenticated users should be able set inactive a service subscription for an organization."""
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    service1 = factories.ServiceFactory()
    service2 = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_nok1, service=service2, operator=operator2
    )

    # Test that no subscription exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/"
    )
    assert response.status_code == 404

    # Test that the subscription can be created with is_active=True (default)
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 201
    content_created = response.json()
    assert "metadata" in content_created
    assert "created_at" in content_created
    assert content_created["is_active"] is True

    # Test that the subscription exists
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/"
    )
    assert response.status_code == 200
    content_retrieved = response.json()
    assert content_retrieved["metadata"] == content_created["metadata"]
    assert content_retrieved["created_at"] == content_created["created_at"]
    assert content_retrieved["is_active"] == content_created["is_active"]

    # Test that the subscription can be set inactive via PATCH
    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/"
    )
    response = client.patch(url, {"is_active": False}, format="json")
    assert response.status_code == 200
    content_updated = response.json()
    assert content_updated["is_active"] is False

    # Test that the subscription is inactive
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/"
        f"services/{service1.id}/subscription/"
    )
    assert response.status_code == 200
    content_retrieved = response.json()
    assert content_retrieved["is_active"] is False

    # Delete the subscription to test creating with is_active=False
    response = client.delete(url)
    assert response.status_code == 204

    # Test that the subscription can be created with is_active=False
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/",
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 201
    content_created_inactive = response.json()
    assert content_created_inactive["is_active"] is False

    # Verify it's inactive
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/"
    )
    assert response.status_code == 200
    content_retrieved = response.json()
    assert content_retrieved["is_active"] is False

    # Test that the subscription can be set active via PATCH
    response = client.patch(url, {"is_active": True}, format="json")
    assert response.status_code == 200
    content_updated = response.json()
    assert content_updated["is_active"] is True


def test_api_organization_service_enable_disable_no_role():
    """
    Authenticated users should not be able to enable and disable a service for an
    organization for which they have no UserOperatorRole.
    """
    user = factories.UserFactory()
    user2 = factories.UserFactory()
    client = APIClient()
    client.force_login(user2)
    operator = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    operator3 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    factories.UserOperatorRoleFactory(user=user2, operator=operator2)
    factories.UserOperatorRoleFactory(user=user2, operator=operator3)

    organization_ok1 = factories.OrganizationFactory(name="A")
    organization_ok2 = factories.OrganizationFactory(name="B")
    organization_nok1 = factories.OrganizationFactory()
    organization_nok2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization_ok2
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok1
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization_nok2
    )

    service1 = factories.ServiceFactory()
    factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization_ok1, service=service1, operator=operator
    )

    # Test that it cannot be retrieved
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/"
    )
    assert response.status_code == 403

    # Test that the subscription cannot be created
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}/services/{service1.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 403

    # Test that the subscription cannot be deleted
    response = client.delete(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization_ok1.id}"
        f"/services/{service1.id}/subscription/"
    )
    assert response.status_code == 403


def test_api_organization_service_subscription_post_not_allowed():
    """Test that POST method is not allowed for subscription endpoint."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    response = client.post(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {},
        format="json",
    )
    assert response.status_code == 405


def test_api_organization_service_subscription_put_not_allowed():
    """Test that PUT method is not allowed for subscription endpoint."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory()
    service = factories.ServiceFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    response = client.put(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 405


def test_api_organization_service_can_activate():
    """Test that the can_activate method returns True if the service has no required services."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is True


def test_api_organization_service_cannot_activate_required_services():
    """Test that it is not possible to activate a service if one of its required services is not activated."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service_required = factories.ServiceFactory(name="Service Required")
    factories.OperatorServiceConfigFactory(operator=operator, service=service_required)

    service = factories.ServiceFactory(name="Service")
    service.required_services.add(service_required)
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the service cannot be activated by default
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is False

    # Check that the subscription cannot be created
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert "missing_required_services" in response.json()["__all__"][0].lower()


def test_api_organization_service_can_update_subscription_when_cannot_activate():
    """Test that it is possible to update a subscription (with is_active=False only) when it cannot be activated."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service_required = factories.ServiceFactory(name="Service Required")
    factories.OperatorServiceConfigFactory(operator=operator, service=service_required)

    service = factories.ServiceFactory(name="Service")
    service.required_services.add(service_required)
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the service cannot be activated by default
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is False

    # Check that the subscription can be created if is_active is False
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"metadata": {"idp_id": "1234567890"}, "is_active": False},
        format="json",
    )
    assert response.status_code == 201

    # Check that the subscription can be updated if is_active is False
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"metadata": {"idp_id": "1234567891"}},
        format="json",
    )
    assert response.status_code == 200


def test_api_organization_service_can_activate_if_required_services_are_activated():
    """Test that activation of a service is possible if all its required services gets activated."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    organization2 = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization2
    )

    service_required = factories.ServiceFactory(name="Service Required")
    factories.OperatorServiceConfigFactory(operator=operator, service=service_required)

    service = factories.ServiceFactory(name="Service")
    service.required_services.add(service_required)
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Check that the service cannot be activated by default
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is False

    # Activate the required service on another organization to verify that
    # there is no collision.

    factories.ServiceSubscriptionFactory(
        organization=organization2, service=service_required, operator=operator
    )

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is False

    # Activate the required service on the first organization

    factories.ServiceSubscriptionFactory(
        organization=organization, service=service_required, operator=operator
    )

    # Check that the service can be activated
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is True


def test_api_services_exposed_config():
    """Test that the exposed config is the expected one."""
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
        config={"help_center_url": "https://www.service.fr", "secret_key": "secret_key"}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # List route.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 200
    keys = list(response.json()["results"][0]["config"].keys())
    assert keys == ["help_center_url"]

    # Retrieve route.
    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    keys = list(response.json()["config"].keys())
    assert keys == ["help_center_url"]


@pytest.mark.parametrize(
    "population,epci_population,expected_can_activate,expected_reason,_description",
    [
        (3000, 20000, True, None, "commune population below limit"),
        (5000, 10000, True, None, "EPCI population below limit"),
        (
            5000,
            20000,
            False,
            "population_limit_exceeded",
            "both populations exceed limits",
        ),
        (None, None, False, "population_limit_exceeded", "both populations are null"),
    ],
)
def test_api_organization_service_commune_population_limits(
    population, epci_population, expected_can_activate, expected_reason, _description
):
    """Test population limit checking for commune organizations."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(
        type="commune", population=population, epci_population=epci_population
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={"population_limits": {"commune": 3500, "epci": 15000}}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is expected_can_activate
    if expected_reason:
        assert content["activation_blocked_reason"] == expected_reason
    else:
        assert "activation_blocked_reason" not in content


@pytest.mark.parametrize(
    "population,expected_can_activate,expected_reason,_description",
    [
        (10000, True, None, "EPCI population below limit"),
        (20000, False, "population_limit_exceeded", "EPCI population above limit"),
        (None, False, "population_limit_exceeded", "EPCI population is null"),
    ],
)
def test_api_organization_service_epci_population_limits(
    population, expected_can_activate, expected_reason, _description
):
    """Test population limit checking for EPCI organizations."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(type="epci", population=population)
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={"population_limits": {"commune": 3500, "epci": 15000}}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is expected_can_activate
    if expected_reason:
        assert content["activation_blocked_reason"] == expected_reason
    else:
        assert "activation_blocked_reason" not in content


@pytest.mark.parametrize(
    "can_bypass,org_type,population,epci_population,expected_can_activate,_description",
    [
        (
            True,
            "commune",
            5000,
            20000,
            True,
            "operator bypass with commune exceeding limits",
        ),
        (True, "epci", 20000, None, True, "operator bypass with EPCI exceeding limit"),
        (
            False,
            "commune",
            5000,
            20000,
            False,
            "no bypass with commune exceeding limits",
        ),
        (False, "epci", 20000, None, False, "no bypass with EPCI exceeding limit"),
    ],
)
def test_api_organization_service_operator_bypass_population_limits(
    can_bypass,
    org_type,
    population,
    epci_population,
    expected_can_activate,
    _description,
):
    """Test operator bypass functionality for population limits."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator_config = {"can_bypass_population_limits": can_bypass} if can_bypass else {}
    operator = factories.OperatorFactory(config=operator_config)
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    org_kwargs = {"type": org_type, "population": population}
    if org_type == "commune":
        org_kwargs["epci_population"] = epci_population
    organization = factories.OrganizationFactory(**org_kwargs)
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={"population_limits": {"commune": 3500, "epci": 15000}}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    response = client.get(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["can_activate"] is expected_can_activate
    if expected_can_activate:
        assert "activation_blocked_reason" not in content
    else:
        assert content["activation_blocked_reason"] == "population_limit_exceeded"


def test_api_organization_service_subscription_validation_population_limits():
    """Test that subscription activation is blocked when population limits are exceeded."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory(
        type="commune", population=5000, epci_population=20000
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(
        config={"population_limits": {"commune": 3500, "epci": 15000}}
    )
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Try to activate subscription
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert "population_limit_exceeded" in response.json()["__all__"][0].lower()


def test_api_organizations_services_list_includes_other_operator_subscription():
    """
    Services list should return the effective subscription (from any operator)
    in the subscription field, with operator_id and operator_name identifying
    who manages it.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator1 = factories.OperatorFactory(name="Operator 1")
    operator2 = factories.OperatorFactory(name="Operator 2", config={"idps": []})
    factories.UserOperatorRoleFactory(user=user, operator=operator1)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator1, organization=organization
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization
    )

    service = factories.ServiceFactory()
    factories.OperatorServiceConfigFactory(operator=operator1, service=service)
    factories.OperatorServiceConfigFactory(operator=operator2, service=service)

    # Create subscription from operator2 (not current operator)
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator2, is_active=True
    )

    response = client.get(
        f"/api/v1.0/operators/{operator1.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 200
    content = response.json()
    results = content["results"]

    service_result = next(r for r in results if r["id"] == service.id)

    # Subscription should now contain the effective subscription (from operator2)
    # with operator info to identify who manages it
    subscription = service_result["subscription"]
    assert subscription is not None
    assert subscription["operator_id"] == str(operator2.id)
    assert subscription["operator_name"] == "Operator 2"
    assert subscription["is_active"] is True
    assert "created_at" in subscription


def test_api_organizations_services_shows_service_with_only_other_operator_subscription():
    """
    Services that only have a subscription from another operator (not current)
    should still appear in the list for visibility. The subscription field
    returns the effective subscription with operator info.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator1 = factories.OperatorFactory(name="Operator 1")
    operator2 = factories.OperatorFactory(name="Operator 2", config={"idps": []})
    factories.UserOperatorRoleFactory(user=user, operator=operator1)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator1, organization=organization
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization
    )

    # Service with NO config for operator1
    service = factories.ServiceFactory()
    factories.OperatorServiceConfigFactory(operator=operator2, service=service)

    # Before creating the subscription, the service should NOT appear
    response = client.get(
        f"/api/v1.0/operators/{operator1.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 200
    service_ids_before = [r["id"] for r in response.json()["results"]]
    assert service.id not in service_ids_before

    # Now create subscription from operator2
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator2
    )

    response = client.get(
        f"/api/v1.0/operators/{operator1.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 200
    content = response.json()

    # Service should appear even though current operator has no config/subscription
    service_ids = [r["id"] for r in content["results"]]
    assert service.id in service_ids

    service_result = next(r for r in content["results"] if r["id"] == service.id)

    # Subscription shows the effective subscription (from operator2) with operator info
    subscription = service_result["subscription"]
    assert subscription is not None
    assert subscription["operator_id"] == str(operator2.id)
    assert subscription["operator_name"] == "Operator 2"

    assert service_result["operator_config"] is None  # No config for current operator


def test_api_organizations_services_permission():
    """
    Verify that services are only visible when current operator manages the organization.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator1 = factories.OperatorFactory()
    operator2 = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator1)

    # Organization NOT managed by operator1
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator2, organization=organization
    )

    service = factories.ServiceFactory()
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator2
    )

    # Should get 403 because operator1 doesn't manage this org
    response = client.get(
        f"/api/v1.0/operators/{operator1.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 403


def test_api_organizations_services_subscription_includes_operator_info():
    """
    Verify that when the current operator has a subscription, it includes operator info.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    operator1 = factories.OperatorFactory(name="Operator 1", config={"idps": []})
    factories.UserOperatorRoleFactory(user=user, operator=operator1)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator1, organization=organization
    )

    service = factories.ServiceFactory()
    factories.OperatorServiceConfigFactory(operator=operator1, service=service)

    # Create subscription from operator1 (current operator)
    factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator1, is_active=True
    )

    response = client.get(
        f"/api/v1.0/operators/{operator1.id}/organizations/{organization.id}/services/"
    )
    assert response.status_code == 200
    content = response.json()
    results = content["results"]

    service_result = next(r for r in results if r["id"] == service.id)

    # Current operator's subscription should be in "subscription" field with operator info
    subscription = service_result["subscription"]
    assert subscription is not None
    assert subscription["is_active"] is True
    assert subscription["operator_id"] == str(operator1.id)
    assert subscription["operator_name"] == "Operator 1"
