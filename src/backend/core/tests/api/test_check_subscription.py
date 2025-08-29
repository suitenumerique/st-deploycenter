"""
Test subscription check API endpoints in the deploycenter core app.
"""

import pytest

from core import factories

pytestmark = pytest.mark.django_db


class TestServiceSubscriptionCheck:
    """Test the service subscription check endpoint."""

    def test_check_service_subscription_with_siret_success(self, api_client):
        """Test successful service subscription check with SIRET."""
        # Create test data
        user = factories.UserFactory()
        operator = factories.OperatorFactory()
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory()
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization, service=service
        )

        # Link operator to organization
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization, role="admin"
        )

        # Authenticate user
        api_client.force_login(user)

        # Test check
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert data["has_subscription"] is True
        assert data["organization_id"] == str(organization.id)
        assert data["organization_name"] == organization.name
        assert data["subscription_id"] == str(subscription.id)
        assert data["service_id"] == str(service.id)
        assert data["service_name"] == service.type
        assert data["error_message"] is None

    def test_check_service_subscription_with_insee_success(self, api_client):
        """Test successful service subscription check with INSEE code."""
        # Create test data
        user = factories.UserFactory()
        operator = factories.OperatorFactory()
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory()
        subscription = factories.ServiceSubscriptionFactory(
            organization=organization, service=service
        )

        # Link operator to organization
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization, role="admin"
        )

        # Authenticate user
        api_client.force_login(user)

        # Test check
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {"insee": organization.code_insee},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert data["has_subscription"] is True
        assert data["organization_id"] == str(organization.id)
        assert data["organization_name"] == organization.name
        assert data["subscription_id"] == str(subscription.id)
        assert data["service_id"] == str(service.id)
        assert data["service_name"] == service.type
        assert data["error_message"] is None

    def test_check_service_subscription_no_subscription(self, api_client):
        """Test service subscription check when organization has no subscription."""
        # Create test data
        user = factories.UserFactory()
        operator = factories.OperatorFactory()
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory()

        # Link operator to organization
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization, role="admin"
        )

        # Authenticate user
        api_client.force_login(user)

        # Test check
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert data["has_subscription"] is False
        assert data["organization_id"] == str(organization.id)
        assert data["organization_name"] == organization.name
        assert data["subscription_id"] is None
        assert data["service_id"] == str(service.id)
        assert data["service_name"] == service.type

        assert "no subscription" in data["error_message"]

    def test_check_service_subscription_organization_not_found(self, api_client):
        """Test service subscription check when organization doesn't exist."""
        # Create test data
        user = factories.UserFactory()
        service = factories.ServiceFactory()

        # Authenticate user
        api_client.force_login(user)

        # Test check with non-existent SIRET
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {"siret": "99999999999999"},
            format="json",
        )

        assert response.status_code == 404
        data = response.json()

        assert data["has_subscription"] is False
        assert "Organization not found" in data["error_message"]

    def test_check_service_subscription_invalid_siret_format(self, api_client):
        """Test service subscription check with invalid SIRET format."""
        # Create test data
        user = factories.UserFactory()
        service = factories.ServiceFactory()

        # Authenticate user
        api_client.force_login(user)

        # Test check with invalid SIRET format
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {
                "siret": "12345"  # Too short
            },
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert data["has_subscription"] is False
        assert "Invalid SIRET format" in data["error_message"]

    def test_check_service_subscription_invalid_insee_format(self, api_client):
        """Test service subscription check with invalid INSEE format."""
        # Create test data
        user = factories.UserFactory()
        service = factories.ServiceFactory()
        api_client.force_login(user)

        # Test check with invalid INSEE format
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {
                "insee": "123"  # Too short
            },
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert data["has_subscription"] is False
        assert "Invalid INSEE format" in data["error_message"]

    def test_check_service_subscription_both_siret_and_insee(self, api_client):
        """Test service subscription check with both SIRET and INSEE provided."""
        # Create test data
        user = factories.UserFactory()
        service = factories.ServiceFactory()

        # Authenticate user
        api_client.force_login(user)

        # Test check with both SIRET and INSEE
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {"siret": "12345678901234", "insee": "12345"},
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert data["has_subscription"] is False
        assert "Cannot provide both" in data["error_message"]

    def test_check_service_subscription_missing_required_fields(self, api_client):
        """Test service subscription check with missing required fields."""
        # Create test data
        user = factories.UserFactory()
        service = factories.ServiceFactory()

        # Authenticate user
        api_client.force_login(user)

        # Test check with missing SIRET and INSEE
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/", {}, format="json"
        )

        assert response.status_code == 400
        data = response.json()

        assert data["has_subscription"] is False
        assert "Must provide either" in data["error_message"]

    def test_check_service_subscription_unauthenticated(self, api_client):
        """Test service subscription check without authentication."""
        # Create test data
        service = factories.ServiceFactory()

        # Test check without authentication
        response = api_client.post(
            f"/api/v1.0/services/{service.id}/check-subscription/",
            {"siret": "12345678901234"},
            format="json",
        )

        assert response.status_code == 401

    def test_check_service_subscription_service_not_found(self, api_client):
        """Test service subscription check with non-existent service."""
        # Create test data
        user = factories.UserFactory()

        # Authenticate user
        api_client.force_login(user)

        # Test check with non-existent service
        response = api_client.post(
            "/api/v1.0/services/00000000-0000-0000-0000-000000000000/check-subscription/",
            {"siret": "12345678901234"},
            format="json",
        )

        assert response.status_code == 404
