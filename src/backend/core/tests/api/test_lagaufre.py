"""
Test Lagaufre API endpoints in the deploycenter core app.
"""

import pytest

from core import factories

pytestmark = pytest.mark.django_db


class TestLagaufreServicesEndpoint:
    """Test the Lagaufre services endpoint."""

    def test_get_services_with_siret_success(self, api_client):
        """Test successful retrieval of services with SIRET."""
        # Create test data
        organization = factories.OrganizationFactory()

        # Create services with different maturities
        service1 = factories.ServiceFactory(
            name="Service Alpha", maturity="alpha", is_active=True
        )
        factories.ServiceFactory(name="Service Beta", maturity="beta", is_active=True)
        service3 = factories.ServiceFactory(
            name="Service Stable", maturity="stable", is_active=True
        )

        # Create subscriptions for some services
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service1
        )
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service3
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Check organization info
        assert data["organization"]["name"] == organization.name
        assert data["organization"]["type"] == organization.type
        assert data["organization"]["siret"] == organization.siret

        # Check services data
        assert len(data["services"]) == 3

        # Check that subscribed services come first
        services = data["services"]
        assert services[0]["subscribed"] is True  # Service Alpha (subscribed)
        assert services[1]["subscribed"] is True  # Service Stable (subscribed)
        assert services[2]["subscribed"] is False  # Service Beta (not subscribed)

        # Check service data structure
        for service_data in services:
            assert "id" in service_data
            assert "name" in service_data
            assert "url" in service_data
            assert "maturity" in service_data
            assert "logo" in service_data
            assert "subscribed" in service_data
            assert isinstance(service_data["subscribed"], bool)

    def test_get_services_with_siren_success(self, api_client):
        """Test successful retrieval of services with SIREN."""
        # Create test data
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.ServiceSubscriptionFactory(organization=organization, service=service)

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siren": organization.siren},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert data["organization"]["siret"] == organization.siret
        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is True

    def test_get_services_with_insee_success(self, api_client):
        """Test successful retrieval of services with INSEE code."""
        # Create test data
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.ServiceSubscriptionFactory(organization=organization, service=service)

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"insee": organization.code_insee},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert data["organization"]["siret"] == organization.siret
        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is True

    def test_get_services_no_subscriptions(self, api_client):
        """Test retrieval when organization has no subscriptions."""
        # Create test data
        organization = factories.OrganizationFactory()
        factories.ServiceFactory(is_active=True)

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is False

    def test_get_services_only_active_services(self, api_client):
        """Test that only active services are returned."""
        # Create test data
        organization = factories.OrganizationFactory()

        # Create active and inactive services
        active_service = factories.ServiceFactory(is_active=True)
        inactive_service = factories.ServiceFactory(is_active=False)

        factories.ServiceSubscriptionFactory(
            organization=organization, service=active_service
        )
        factories.ServiceSubscriptionFactory(
            organization=organization, service=inactive_service
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Only active service should be returned
        assert len(data["services"]) == 1
        assert data["services"][0]["id"] == active_service.id

    def test_get_services_logo_url_generation(self, api_client):
        """Test that logo URLs are properly generated."""
        # Create test data
        organization = factories.OrganizationFactory()

        # Create services with and without logos
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg>'
        service_with_logo = factories.ServiceFactory(
            is_active=True, logo_svg=svg_content
        )
        service_without_logo = factories.ServiceFactory(is_active=True, logo_svg=None)

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Check logo URLs
        services = data["services"]
        service_with_logo_data = next(
            s for s in services if s["id"] == service_with_logo.id
        )
        service_without_logo_data = next(
            s for s in services if s["id"] == service_without_logo.id
        )

        assert (
            service_with_logo_data["logo"]
            == f"/api/v1.0/servicelogo/{service_with_logo.id}/"
        )
        assert service_without_logo_data["logo"] is None

    def test_get_services_organization_not_found(self, api_client):
        """Test 404 when organization doesn't exist."""
        # Create test data

        # No authentication required for anonymous API

        # Test request with non-existent SIRET
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": "99999999999999"},
            format="json",
        )

        assert response.status_code == 404
        data = response.json()

        assert "Organization not found" in data["error"]
        assert data["services"] == []

    def test_get_services_invalid_siret_format(self, api_client):
        """Test 400 with invalid SIRET format."""
        # Create test data

        # No authentication required for anonymous API

        # Test request with invalid SIRET format
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": "12345"},  # Too short
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert "siret" in data["error"]
        assert "Invalid SIRET format" in data["error"]["siret"][0]
        assert data["services"] == []

    def test_get_services_invalid_siren_format(self, api_client):
        """Test 400 with invalid SIREN format."""
        # Create test data

        # No authentication required for anonymous API

        # Test request with invalid SIREN format
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siren": "123"},  # Too short
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert "siren" in data["error"]
        assert "Invalid SIREN format" in data["error"]["siren"][0]
        assert data["services"] == []

    def test_get_services_invalid_insee_format(self, api_client):
        """Test 400 with invalid INSEE format."""
        # Create test data

        # No authentication required for anonymous API

        # Test request with invalid INSEE format
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"insee": "123"},  # Too short
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert "insee" in data["error"]
        assert "Invalid INSEE format" in data["error"]["insee"][0]
        assert data["services"] == []

    def test_get_services_multiple_identifiers(self, api_client):
        """Test 400 when multiple identifiers are provided."""
        # Create test data

        # No authentication required for anonymous API

        # Test request with multiple identifiers
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": "12345678901234", "siren": "123456789"},
            format="json",
        )

        assert response.status_code == 400
        data = response.json()

        assert "non_field_errors" in data["error"]
        assert (
            "Cannot provide multiple identifiers"
            in data["error"]["non_field_errors"][0]
        )
        assert data["services"] == []

    def test_get_services_no_identifiers(self, api_client):
        """Test organization-less mode when no identifiers are provided."""
        # Create test data
        factories.ServiceFactory(is_active=True)

        # No authentication required for anonymous API

        # Test request with no identifiers (should work in organization-less mode)
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Should return services without organization info
        assert "organization" not in data
        assert len(data["services"]) == 1
        assert "subscribed" not in data["services"][0]

    def test_get_services_anonymous_access(self, api_client):
        """Test that anonymous users can access the API."""
        # Create test data
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.ServiceSubscriptionFactory(organization=organization, service=service)

        # Test request without authentication (should work now)
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is True

    def test_get_services_empty_string_identifiers(self, api_client):
        """Test organization-less mode with empty string identifiers."""
        # Create test data
        factories.ServiceFactory(is_active=True)

        # No authentication required for anonymous API

        # Test request with empty string identifiers (should work in organization-less mode)
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": "", "siren": "", "insee": ""},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Should return services without organization info
        assert "organization" not in data
        assert len(data["services"]) == 1
        assert "subscribed" not in data["services"][0]

    def test_get_services_whitespace_identifiers(self, api_client):
        """Test that whitespace in identifiers is handled correctly."""
        # Create test data
        organization = factories.OrganizationFactory()
        factories.ServiceFactory(is_active=True)

        # No authentication required for anonymous API

        # Test request with whitespace around SIRET
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": f"  {organization.siret}  "},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert data["organization"]["siret"] == organization.siret
        assert len(data["services"]) == 1

    def test_get_services_ordering_by_subscription_status(self, api_client):
        """Test that services are properly ordered by subscription status."""
        # Create test data
        organization = factories.OrganizationFactory()

        # Create services with specific names for predictable ordering
        service_a = factories.ServiceFactory(name="Service A", is_active=True)
        factories.ServiceFactory(name="Service B", is_active=True)
        service_c = factories.ServiceFactory(name="Service C", is_active=True)
        factories.ServiceFactory(name="Service D", is_active=True)

        # Subscribe to services A and C (not B and D)
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service_a
        )
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service_c
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        services = data["services"]
        assert len(services) == 4

        # First two should be subscribed (A and C)
        assert services[0]["subscribed"] is True
        assert services[1]["subscribed"] is True

        # Last two should be unsubscribed (B and D)
        assert services[2]["subscribed"] is False
        assert services[3]["subscribed"] is False

        # Within each group, they should be ordered by name
        subscribed_names = [s["name"] for s in services[:2]]
        unsubscribed_names = [s["name"] for s in services[2:]]

        assert subscribed_names == ["Service A", "Service C"]
        assert unsubscribed_names == ["Service B", "Service D"]

    def test_get_services_organization_less_mode(self, api_client):
        """Test organization-less mode returns all services without subscription info."""
        # Create test data

        # Create services with different maturities
        factories.ServiceFactory(name="Service Alpha", maturity="alpha", is_active=True)
        factories.ServiceFactory(name="Service Beta", maturity="beta", is_active=True)
        factories.ServiceFactory(
            name="Service Stable", maturity="stable", is_active=True
        )

        # Create an inactive service (should not be returned)
        factories.ServiceFactory(name="Inactive Service", is_active=False)

        # No authentication required for anonymous API

        # Test request with no organization identifier
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Check that no organization info is returned
        assert "organization" not in data

        # Check services data
        assert len(data["services"]) == 3  # Only active services
        services = data["services"]

        # Check that services are ordered by name
        assert services[0]["name"] == "Service Alpha"
        assert services[1]["name"] == "Service Beta"
        assert services[2]["name"] == "Service Stable"

        # Check that no subscription info is included
        for service_data in services:
            assert "subscribed" not in service_data
            assert "id" in service_data
            assert "name" in service_data
            assert "url" in service_data
            assert "maturity" in service_data
            assert "logo" in service_data

        # Verify inactive service is not included
        service_names = [s["name"] for s in services]
        assert "Inactive Service" not in service_names

    def test_get_services_organization_less_mode_with_empty_strings(self, api_client):
        """Test organization-less mode with empty string identifiers."""
        # Create test data
        factories.ServiceFactory(is_active=True)

        # No authentication required for anonymous API

        # Test request with empty string identifiers
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": "", "siren": "", "insee": ""},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Check that no organization info is returned
        assert "organization" not in data
        assert len(data["services"]) == 1
        assert "subscribed" not in data["services"][0]

    def test_get_services_organization_less_mode_with_whitespace(self, api_client):
        """Test organization-less mode with whitespace-only identifiers."""
        # Create test data
        factories.ServiceFactory(is_active=True)

        # No authentication required for anonymous API

        # Test request with whitespace-only identifiers
        response = api_client.post(
            "/api/v1.0/lagaufre/services/",
            {"siret": "   ", "siren": "  ", "insee": " "},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Check that no organization info is returned
        assert "organization" not in data
        assert len(data["services"]) == 1
        assert "subscribed" not in data["services"][0]
