"""
Tests for DPNT (Données de la Présence Numérique des Territoires) import functionality.

This module tests the DPNT dataset download and import tasks with real data from data.gouv.fr.
"""

import logging

import pytest

from core.models import Organization
from core.tasks.dpnt import import_dpnt_dataset

logger = logging.getLogger(__name__)


@pytest.mark.django_db
def test_import_real_dpnt_data():
    """Test importing real DPNT data (first 100 rows) and verify the import."""
    # Clear existing data to start fresh
    assert Organization.objects.count() == 0

    # Run the import task with max_rows=100 for testing
    logger.info("Running DPNT import task with max_rows=100...")
    result = import_dpnt_dataset.apply(
        kwargs={"force_update": False, "max_rows": 100}
    ).get()

    # Verify import results
    assert result["total_processed"] >= 100  # Should be limited by max_rows, by type
    assert result["created"] == result["total_processed"], (
        "No organizations were created"
    )
    assert result["errors"] == 0, "Unexpected error count"

    logger.info(
        "Import completed: %d created, %d updated, %d errors",
        result["created"],
        result["updated"],
        result["errors"],
    )

    # Verify organizations were created in the database
    created_orgs = Organization.objects.all()
    assert created_orgs.count() == result["total_processed"], (
        "No organizations found in database"
    )

    logger.info("Found %d organizations in database", created_orgs.count())

    # Check a sample organizations to verify field mapping
    sample_org = created_orgs.filter(type="commune").first()
    logger.info(
        "Sample organization: %s (INSEE: %s)", sample_org.name, sample_org.code_insee
    )

    # Verify required fields are populated
    assert sample_org.name, "Organization name is empty"
    assert sample_org.type, "Organization type is empty"
    assert sample_org.code_insee, "Organization INSEE code is empty"

    # Verify field types and values
    if sample_org.population:
        assert isinstance(sample_org.population, int), "Population should be integer"
        assert sample_org.population > 0, "Population should be positive"

    if sample_org.code_postal:
        assert isinstance(sample_org.code_postal, str), "Postal code should be string"
        assert len(sample_org.code_postal) > 0, "Postal code should not be empty"

    if sample_org.siret:
        assert isinstance(sample_org.siret, str), "SIRET should be string"
        assert len(sample_org.siret) == 14, "SIRET should be 14 characters"

    if sample_org.siren:
        assert isinstance(sample_org.siren, str), "SIREN should be string"
        assert len(sample_org.siren) == 9, "SIREN should be 9 characters"

    logger.info("✅ DPNT import test completed successfully!")
    logger.info("Total organizations imported: %d", created_orgs.count())
    logger.info("Import statistics: %s", result)

    # Change the sample org population
    sample_org.population += 1
    sample_org.save()

    # Run the import task with max_rows=100 for testing
    logger.info("Running DPNT import task with max_rows=100...")
    result = import_dpnt_dataset.apply(
        kwargs={"force_update": True, "max_rows": 100}
    ).get()

    # Verify import results
    assert result["total_processed"] >= 100  # Should be limited by max_rows
    assert result["created"] == 0, "No organizations were created"
    assert result["updated"] == result["total_processed"], "No organization was updated"

    sample_org_2 = Organization.objects.get(code_insee=sample_org.code_insee)

    # Make sure the population was updated back to the original value
    assert sample_org_2.population == sample_org.population - 1

    # Make sure no new orgs were created in the update
    assert Organization.objects.count() == result["total_processed"]
