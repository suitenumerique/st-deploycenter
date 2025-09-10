"""
Test service logo API endpoints in the deploycenter core app.
"""

# pylint: disable=line-too-long

import pytest

from core import factories

pytestmark = pytest.mark.django_db


class TestServiceLogoViewSet:
    """Test the service logo endpoint."""

    def test_get_service_logo_success(self, api_client):
        """Test successful retrieval of service logo."""
        # Create test data with logo
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="blue"/></svg>'
        service = factories.ServiceFactory(is_active=True, logo_svg=svg_content)

        # Test GET request (no authentication required)
        response = api_client.get(f"/api/v1.0/servicelogo/{service.id}/")

        assert response.status_code == 200
        assert response["Content-Type"] == "image/svg+xml; charset=utf-8"
        assert response["Content-Disposition"] == 'inline; filename="logo.svg"'
        assert response["Cache-Control"] == "public, max-age=3600"
        assert response["Access-Control-Allow-Origin"] == "*"
        assert response.content == svg_content

    def test_get_service_logo_not_found(self, api_client):
        """Test 404 when service doesn't exist."""
        # Test with non-existent service ID
        response = api_client.get("/api/v1.0/servicelogo/99999/")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "No Service matches the given query."

    def test_get_service_logo_no_logo(self, api_client):
        """Test 404 when service exists but has no logo."""
        # Create service without logo
        service = factories.ServiceFactory(is_active=True, logo_svg=None)

        response = api_client.get(f"/api/v1.0/servicelogo/{service.id}/")

        assert response.status_code == 404
        assert response.json()

    def test_get_service_logo_inactive_service(self, api_client):
        """Test 404 when service is inactive."""
        # Create inactive service with logo
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="blue"/></svg>'
        service = factories.ServiceFactory(is_active=False, logo_svg=svg_content)

        response = api_client.get(f"/api/v1.0/servicelogo/{service.id}/")

        assert response.status_code == 404

    def test_get_service_logo_empty_logo(self, api_client):
        """Test 404 when service has empty logo."""
        # Create service with empty logo
        service = factories.ServiceFactory(is_active=True, logo_svg=b"")

        response = api_client.get(f"/api/v1.0/servicelogo/{service.id}/")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Logo not found for this service"

    def test_get_service_logo_unicode_content(self, api_client):
        """Test service logo with unicode content."""
        # Create test data with unicode SVG content
        svg_content = '<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><text x="50" y="50" text-anchor="middle">Testé</text></svg>'.encode(
            "utf-8"
        )
        service = factories.ServiceFactory(is_active=True, logo_svg=svg_content)

        response = api_client.get(f"/api/v1.0/servicelogo/{service.id}/")

        assert response.status_code == 200
        assert response["Content-Type"] == "image/svg+xml; charset=utf-8"
        assert response.content == svg_content
