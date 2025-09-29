"""
Test OrganizationIdentifierSerializer in the deploycenter core app.
"""

import pytest

from core import factories
from core.api.serializers import OrganizationIdentifierSerializer

pytestmark = pytest.mark.django_db


class TestOrganizationIdentifierSerializer:
    """Test the OrganizationIdentifierSerializer."""

    def test_valid_siret(self):
        """Test serializer with valid SIRET."""
        organization = factories.OrganizationFactory()

        serializer = OrganizationIdentifierSerializer(
            data={"siret": organization.siret}
        )
        assert serializer.is_valid()

        retrieved_organization = serializer.get_organization()
        assert retrieved_organization == organization
        assert serializer.validated_data["_identifier_type"] == "siret"
        assert serializer.validated_data["_identifier_value"] == organization.siret

    def test_valid_siren(self):
        """Test serializer with valid SIREN."""
        organization = factories.OrganizationFactory()

        serializer = OrganizationIdentifierSerializer(
            data={"siren": organization.siren}
        )
        assert serializer.is_valid()

        retrieved_organization = serializer.get_organization()
        assert retrieved_organization == organization
        assert serializer.validated_data["_identifier_type"] == "siren"
        assert serializer.validated_data["_identifier_value"] == organization.siren

    def test_valid_insee(self):
        """Test serializer with valid INSEE code."""
        organization = factories.OrganizationFactory()

        serializer = OrganizationIdentifierSerializer(
            data={"insee": organization.code_insee}
        )
        assert serializer.is_valid()

        retrieved_organization = serializer.get_organization()
        assert retrieved_organization == organization
        assert serializer.validated_data["_identifier_type"] == "insee"
        assert serializer.validated_data["_identifier_value"] == organization.code_insee

    def test_invalid_siret_format(self):
        """Test serializer with invalid SIRET format."""
        serializer = OrganizationIdentifierSerializer(data={"siret": "12345"})
        assert not serializer.is_valid()
        assert "siret" in serializer.errors
        assert "Invalid SIRET format" in serializer.errors["siret"][0]

    def test_invalid_siren_format(self):
        """Test serializer with invalid SIREN format."""
        serializer = OrganizationIdentifierSerializer(data={"siren": "123"})
        assert not serializer.is_valid()
        assert "siren" in serializer.errors
        assert "Invalid SIREN format" in serializer.errors["siren"][0]

    def test_invalid_insee_format(self):
        """Test serializer with invalid INSEE format."""
        serializer = OrganizationIdentifierSerializer(data={"insee": "123"})
        assert not serializer.is_valid()
        assert "insee" in serializer.errors
        assert "Invalid INSEE format" in serializer.errors["insee"][0]

    def test_multiple_identifiers(self):
        """Test serializer with multiple identifiers."""
        serializer = OrganizationIdentifierSerializer(
            data={"siret": "12345678901234", "siren": "123456789"}
        )
        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors
        assert (
            "Cannot provide multiple identifiers"
            in serializer.errors["non_field_errors"][0]
        )

    def test_no_identifiers(self):
        """Test serializer with no identifiers (organization-less mode)."""
        serializer = OrganizationIdentifierSerializer(data={})
        assert serializer.is_valid()
        # Should not have identifier info
        assert "_identifier_type" not in serializer.validated_data
        assert "_identifier_value" not in serializer.validated_data

    def test_empty_string_identifiers(self):
        """Test serializer with empty string identifiers (organization-less mode)."""
        serializer = OrganizationIdentifierSerializer(
            data={"siret": "", "siren": "", "insee": ""}
        )
        assert serializer.is_valid()
        # Should not have identifier info
        assert "_identifier_type" not in serializer.validated_data
        assert "_identifier_value" not in serializer.validated_data

    def test_get_organization_no_identifier(self):
        """Test get_organization when no identifier is provided."""
        serializer = OrganizationIdentifierSerializer(data={})
        assert serializer.is_valid()

        organization = serializer.get_organization()
        assert organization is None

    def test_whitespace_identifiers(self):
        """Test serializer with whitespace around identifiers."""
        organization = factories.OrganizationFactory()

        serializer = OrganizationIdentifierSerializer(
            data={"siret": f"  {organization.siret}  "}
        )
        assert serializer.is_valid()

        retrieved_organization = serializer.get_organization()
        assert retrieved_organization == organization
        assert serializer.validated_data["_identifier_value"] == organization.siret

    def test_organization_not_found(self):
        """Test serializer when organization is not found."""
        serializer = OrganizationIdentifierSerializer(data={"siret": "99999999999999"})
        assert serializer.is_valid()

        with pytest.raises(Exception) as exc_info:
            serializer.get_organization()

        assert "Organization not found" in str(exc_info.value)
