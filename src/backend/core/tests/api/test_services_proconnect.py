"""
Test ProConnect services API endpoints in the deploycenter core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db


def test_api_organization_proconnect_service_cannot_activate_if_mail_domain_is_not_set():
    """Test that it is not possible to activate a ProConnect service if the mail domain or IDP is not set."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(type="proconnect")
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
        {"metadata": {"idp_id": "1234567890"}, "is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {
        "__all__": ["Mail domain is required for ProConnect subscription."]
    }


def test_api_organization_proconnect_service_cannot_activate_if_idp_is_not_set():
    """Test that it is not possible to activate a ProConnect service if the IDP is not set."""
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
    service = factories.ServiceFactory(type="proconnect")
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
        {"metadata": {"idp_id": "1234567890"}, "is_active": True},
        format="json",
    )
    assert response.status_code == 201


def test_api_organization_proconnect_service_can_update_subscription_to_set_idp():
    """Test that it is possible to update a ProConnect subscription to set the IDP."""
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
    service = factories.ServiceFactory(type="proconnect")
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
        {"metadata": {"idp_id": "1234567890"}, "is_active": False},
        format="json",
    )
    assert response.status_code == 201


def test_api_organization_proconnect_subscription_idp_name():
    """Test that the IDP name is displayed in the subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory(
        config={"idps": [{"id": "1", "name": "IDP 1"}, {"id": "2", "name": "IDP 2"}]}
    )
    factories.UserOperatorRoleFactory(user=user, operator=operator)

    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )

    service = factories.ServiceFactory(type="proconnect")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    subscription = factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"idp_id": "2"},
        is_active=False,
    )
    assert subscription.idp_name == "IDP 2"


def test_api_organization_proconnect_subscription_cannot_update_idp_id_when_active():
    """Test that it is not possible to update idp_id for an active ProConnect subscription."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory(
        config={"idps": [{"id": "1", "name": "IDP 1"}, {"id": "2", "name": "IDP 2"}]}
    )
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    organization = factories.OrganizationFactory(
        rpnt=["1.1", "1.2", "2.1", "2.2", "2.3"],
        adresse_messagerie="contact@commune.fr",
        site_internet="https://www.commune.fr",
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="proconnect")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)

    # Create an active subscription with idp_id
    subscription = factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"idp_id": "1"},
        is_active=True,
    )

    # Try to update idp_id while subscription is active - should fail
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"metadata": {"idp_id": "2"}},
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {
        "metadata": [
            "Cannot update idp_id for an active ProConnect subscription. "
            "Deactivate the subscription first to change the IDP."
        ]
    }

    # Verify the idp_id was not changed
    subscription.refresh_from_db()
    assert subscription.metadata.get("idp_id") == "1"

    # But we should be able to update other metadata fields
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {
            "metadata": {
                "idp_id": "1",
                "other_field": "value",
                "domains": ["domain.com"],
            }
        },
        format="json",
    )
    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.metadata.get("idp_id") == "1"
    assert (
        subscription.metadata.get("other_field") is None
    )  # No other updates allowed for ProConnect
    assert subscription.metadata.get("domains") == ["commune.fr"]  # Domain is forced

    # We should be able to update idp_id if we deactivate first
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 200

    # Now we can update idp_id
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"metadata": {"idp_id": "2"}},
        format="json",
    )
    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.metadata.get("idp_id") == "2"

    # We should not be able to update idp and activate at the same time
    response = client.patch(
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}/services/{service.id}/subscription/",
        {"metadata": {"idp_id": "3"}, "is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {
        "metadata": [
            "Cannot update idp_id for an active ProConnect subscription. "
            "Deactivate the subscription first to change the IDP."
        ]
    }
