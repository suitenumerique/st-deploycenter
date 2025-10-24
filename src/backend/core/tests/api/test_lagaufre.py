# pylint: disable=too-many-public-methods

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
        operator = factories.OperatorFactory()
        # Create services with different maturities
        service1 = factories.ServiceFactory(
            name="Service Alpha", maturity="alpha", is_active=True
        )
        service2 = factories.ServiceFactory(
            name="Service Beta", maturity="beta", is_active=True
        )
        service3 = factories.ServiceFactory(
            name="Service Stable", maturity="stable", is_active=True
        )

        # Create subscriptions for some services
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service1, operator=operator
        )
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service3, operator=operator
        )

        operator = factories.OperatorFactory()

        factories.OperatorServiceConfigFactory(
            operator=operator, service=service1, display_priority=1
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service2, display_priority=3
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service3, display_priority=2
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": operator.id},
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
        operator = factories.OperatorFactory()
        # Create test data
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service, operator=operator
        )
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siren": organization.siren, "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["organization"]["siret"] == organization.siret
        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is True

    def test_get_services_with_insee_success(self, api_client):
        """Test successful retrieval of services with INSEE code."""
        operator = factories.OperatorFactory()
        # Create test data
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service, operator=operator
        )
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"insee": organization.code_insee, "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["organization"]["siret"] == organization.siret
        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is True

    def test_get_services_no_subscriptions(self, api_client):
        """Test retrieval when organization has no subscriptions."""
        operator = factories.OperatorFactory()
        # Create test data
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is False

    def test_get_services_only_active_services(self, api_client):
        """Test that only active services are returned."""
        # Create test data
        organization = factories.OrganizationFactory()
        operator = factories.OperatorFactory()

        # Create active and inactive services
        active_service = factories.ServiceFactory(is_active=True)
        inactive_service = factories.ServiceFactory(is_active=False)

        factories.ServiceSubscriptionFactory(
            organization=organization, service=active_service, operator=operator
        )
        factories.ServiceSubscriptionFactory(
            organization=organization, service=inactive_service, operator=operator
        )

        # Create operator config only for active service
        factories.OperatorServiceConfigFactory(
            operator=operator, service=active_service
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": operator.id},
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
        operator = factories.OperatorFactory()

        # Create services with and without logos
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg>'
        service_with_logo = factories.ServiceFactory(
            is_active=True, logo_svg=svg_content
        )
        service_without_logo = factories.ServiceFactory(is_active=True, logo_svg=None)

        # Create operator configs for both services
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_with_logo
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_without_logo
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": operator.id},
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
            == f"http://localhost:8961/api/v1.0/servicelogo/{service_with_logo.id}/"
        )
        assert service_without_logo_data["logo"] is None

    def test_get_services_organization_not_found(self, api_client):
        """Test 404 when organization doesn't exist."""
        # Create test data
        operator = factories.OperatorFactory()

        # No authentication required for anonymous API

        # Test request with non-existent SIRET
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": "99999999999999", "operator": operator.id},
        )

        assert response.status_code == 404
        data = response.json()

        assert "Organization not found" in data["error"]
        assert data["services"] == []

    def test_get_services_invalid_siret_format(self, api_client):
        """Test 400 with invalid SIRET format."""
        # Create test data
        operator = factories.OperatorFactory()

        # No authentication required for anonymous API

        # Test request with invalid SIRET format
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": "12345", "operator": operator.id},  # Too short
        )

        assert response.status_code == 400
        data = response.json()

        assert "siret" in data["error"]
        assert "Invalid SIRET format" in data["error"]["siret"][0]
        assert data["services"] == []

    def test_get_services_invalid_siren_format(self, api_client):
        """Test 400 with invalid SIREN format."""
        # Create test data
        operator = factories.OperatorFactory()

        # No authentication required for anonymous API

        # Test request with invalid SIREN format
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siren": "123", "operator": operator.id},  # Too short
        )

        assert response.status_code == 400
        data = response.json()

        assert "siren" in data["error"]
        assert "Invalid SIREN format" in data["error"]["siren"][0]
        assert data["services"] == []

    def test_get_services_invalid_insee_format(self, api_client):
        """Test 400 with invalid INSEE format."""
        # Create test data
        operator = factories.OperatorFactory()

        # No authentication required for anonymous API

        # Test request with invalid INSEE format
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"insee": "123", "operator": operator.id},  # Too short
        )

        assert response.status_code == 400
        data = response.json()

        assert "insee" in data["error"]
        assert "Invalid INSEE format" in data["error"]["insee"][0]
        assert data["services"] == []

    def test_get_services_multiple_identifiers(self, api_client):
        """Test 400 when multiple identifiers are provided."""
        # Create test data
        operator = factories.OperatorFactory()

        # No authentication required for anonymous API

        # Test request with multiple identifiers
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": "12345678901234", "siren": "123456789", "operator": operator.id},
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
        operator = factories.OperatorFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request with no identifiers (organization-less mode)
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"operator": operator.id},
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
        operator = factories.OperatorFactory()
        organization = factories.OrganizationFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service, operator=operator
        )
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # Test request without authentication (should work now)
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["services"]) == 1
        assert data["services"][0]["subscribed"] is True

    def test_get_services_empty_string_identifiers(self, api_client):
        """Test organization-less mode with empty string identifiers."""
        # Create test data
        operator = factories.OperatorFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request with empty string identifiers (should work in organization-less mode)
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": "", "siren": "", "insee": "", "operator": operator.id},
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
        operator = factories.OperatorFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request with whitespace around SIRET
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": f"  {organization.siret}  ", "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["organization"]["siret"] == organization.siret
        assert len(data["services"]) == 1

    def test_get_services_ordering_by_subscription_status(self, api_client):
        """Test that services are properly ordered by subscription status."""
        # Create test data
        organization = factories.OrganizationFactory()
        operator = factories.OperatorFactory()

        # Create services with specific names for predictable ordering
        service_a = factories.ServiceFactory(name="Service A", is_active=True)
        service_b = factories.ServiceFactory(name="Service B", is_active=True)
        service_c = factories.ServiceFactory(name="Service C", is_active=True)
        service_d = factories.ServiceFactory(name="Service D", is_active=True)

        # Subscribe to services A and C (not B and D)
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service_a, operator=operator
        )
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service_c, operator=operator
        )

        # Create operator configs with display priorities
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_a, display_priority=4
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_b, display_priority=3
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_c, display_priority=2
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_d, display_priority=1
        )

        # No authentication required for anonymous API

        # Test request
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()

        services = data["services"]
        assert len(services) == 4

        # Services should be ordered by display priority (descending)
        assert services[0]["name"] == "Service A"
        assert services[1]["name"] == "Service C"
        assert services[2]["name"] == "Service B"
        assert services[3]["name"] == "Service D"

        # Check subscription status
        for service_data in services:
            service_name = service_data["name"]
            if service_name in ["Service A", "Service C"]:
                assert service_data["subscribed"] is True
            else:
                assert service_data["subscribed"] is False

    def test_get_services_organization_less_mode(self, api_client):
        """Test organization-less mode returns all services without subscription info."""
        # Create test data
        operator = factories.OperatorFactory()

        # Create services with different maturities
        service_alpha = factories.ServiceFactory(
            name="Service Alpha", maturity="alpha", is_active=True
        )
        service_beta = factories.ServiceFactory(
            name="Service Beta", maturity="beta", is_active=True
        )
        service_stable = factories.ServiceFactory(
            name="Service Stable", maturity="stable", is_active=True
        )

        # Create an inactive service (should not be returned)
        factories.ServiceFactory(name="Inactive Service", is_active=False)

        # Create operator configs for active services only
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_alpha, display_priority=3
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_beta, display_priority=2
        )
        factories.OperatorServiceConfigFactory(
            operator=operator, service=service_stable, display_priority=1
        )

        # No authentication required for anonymous API

        # Test request with no organization identifier but with deploycenter
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"operator": operator.id},
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

    def test_get_services_missing_operator_parameter(self, api_client):
        """Test that missing operator parameter returns 400 error."""
        # Create test data
        organization = factories.OrganizationFactory()

        # Test request without operator parameter
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret},
        )

        assert response.status_code == 400

    def test_get_services_invalid_operator_id(self, api_client):
        """Test that invalid operator ID returns 400 error."""
        # Create test data
        organization = factories.OrganizationFactory()

        # Test request with invalid operator ID
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": organization.siret, "operator": "invalid-uuid"},
        )

        assert response.status_code == 400

    def test_get_services_organization_less_mode_with_empty_strings(self, api_client):
        """Test organization-less mode with empty string identifiers."""
        # Create test data
        operator = factories.OperatorFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request with empty string identifiers
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": "", "siren": "", "insee": "", "operator": operator.id},
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
        operator = factories.OperatorFactory()
        service = factories.ServiceFactory(is_active=True)
        factories.OperatorServiceConfigFactory(operator=operator, service=service)

        # No authentication required for anonymous API

        # Test request with whitespace-only identifiers
        response = api_client.get(
            "/api/v1.0/lagaufre/services/",
            {"siret": "   ", "siren": "  ", "insee": " ", "operator": operator.id},
        )

        assert response.status_code == 200
        data = response.json()

        # Check that no organization info is returned
        assert "organization" not in data
        assert len(data["services"]) == 1
        assert "subscribed" not in data["services"][0]
