"""
Tests for DPNT (Données de la Présence Numérique des Territoires) import functionality.

This module tests the DPNT dataset download and import tasks with real data from data.gouv.fr.
"""

import logging
from unittest.mock import patch

import pytest

from core.factories import (
    OperatorFactory,
    OperatorServiceConfigFactory,
    OrganizationFactory,
    ServiceFactory,
    ServiceSubscriptionFactory,
)
from core.models import (
    OperatorOrganizationRole,
    Organization,
    ServiceSubscription,
)
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


# Fake DPNT dataset for auto_join tests (bypasses the 30000-row minimum check)
FAKE_DPNT_DATA = [
    {"type": t, **d}
    for t, d in [
        (
            "commune",
            {
                "libelle": "Commune A",
                "siret": "11111111100001",
                "siren": "111111111",
                "code_insee": "00001",
                "code_postal": "75001",
                "population": 5000,
            },
        ),
        (
            "commune",
            {
                "libelle": "Commune B",
                "siret": "22222222200002",
                "siren": "222222222",
                "code_insee": "00002",
                "code_postal": "75002",
                "population": 3000,
            },
        ),
        (
            "epci",
            {
                "libelle": "EPCI Alpha",
                "siret": "33333333300003",
                "siren": "333333333",
                "population": 80000,
            },
        ),
        (
            "departement",
            {
                "libelle": "Dept X",
                "siret": "44444444400004",
                "siren": "444444444",
                "departement_code_insee": "01",
                "population": 500000,
            },
        ),
        (
            "departement",
            {
                "libelle": "Dept Y",
                "siret": "55555555500005",
                "siren": "555555555",
                "departement_code_insee": "02",
                "population": 600000,
            },
        ),
    ]
]
# Pad to 30001 items so the import doesn't reject it
FAKE_DPNT_DATA += [
    {
        "type": "commune",
        "libelle": f"Padding {i}",
        "siret": f"{60000000000000 + i}",
        "siren": f"{600000000 + i:09d}",
        "code_insee": f"{10000 + i:05d}",
        "code_postal": "99999",
        "population": 100,
    }
    for i in range(30001 - len(FAKE_DPNT_DATA))
]


def _mock_download():
    """Return a successful fake download result."""
    return {
        "status": "success",
        "message": f"Downloaded {len(FAKE_DPNT_DATA)} records",
        "data": FAKE_DPNT_DATA,
    }


@pytest.mark.django_db
@patch("core.tasks.dpnt.download_dpnt_dataset", side_effect=_mock_download)
def test_dpnt_auto_join(_mock_dl):
    """Test that auto_join config on Operators creates roles and subscriptions."""

    # -- Setup: operator, services, operator-service configs --
    operator = OperatorFactory()
    valid_service = ServiceFactory()
    unconfigured_service = ServiceFactory()

    # Only valid_service has an OperatorServiceConfig
    OperatorServiceConfigFactory(operator=operator, service=valid_service)
    # No OperatorServiceConfig for unconfigured_service

    operator.config = {
        "auto_join": {
            "types": ["commune", "epci"],
            "services": [valid_service.id, unconfigured_service.id],
        }
    }
    operator.save()

    # -- Pre-existing organizations with subscriptions --
    pre_existing_active_org = OrganizationFactory(
        type="commune", siret="99999999900001", siren="999999999", code_insee="99001"
    )
    pre_existing_inactive_org = OrganizationFactory(
        type="commune", siret="99999999900002", siren="999999998", code_insee="99002"
    )

    # Active subscription for pre_existing_active_org
    ServiceSubscriptionFactory(
        operator=operator,
        organization=pre_existing_active_org,
        service=valid_service,
    )
    assert (
        ServiceSubscription.objects.get(
            organization=pre_existing_active_org, service=valid_service
        ).is_active
        is True
    )

    # Inactive subscription for pre_existing_inactive_org
    inactive_sub = ServiceSubscriptionFactory(
        operator=operator,
        organization=pre_existing_inactive_org,
        service=valid_service,
    )
    inactive_sub.is_active = False
    inactive_sub.save()

    # -- Run import --
    with patch("core.tasks.dpnt.logger") as mock_logger:
        result = import_dpnt_dataset.apply(
            kwargs={"force_update": True, "max_rows": 5}
        ).get()

    # -- Assertions --

    # 1. Stats contain auto_join key
    assert "auto_join" in result
    auto_join_stats = result["auto_join"]
    assert "roles_created" in auto_join_stats
    assert "subscriptions_created" in auto_join_stats

    # 2. Commune and EPCI orgs from DPNT + pre-existing commune orgs
    commune_epci_orgs = Organization.objects.filter(type__in=["commune", "epci"])
    dept_orgs = Organization.objects.filter(type="departement")

    # 3. OperatorOrganizationRole: exists for all commune/epci orgs, not for departement
    for org in commune_epci_orgs:
        assert OperatorOrganizationRole.objects.filter(
            operator=operator, organization=org
        ).exists(), f"Missing role for {org.name} ({org.type})"

    for org in dept_orgs:
        assert not OperatorOrganizationRole.objects.filter(
            operator=operator, organization=org
        ).exists(), f"Unexpected role for departement org {org.name}"

    # 4. ServiceSubscription: exists for commune/epci + valid_service
    for org in commune_epci_orgs:
        assert ServiceSubscription.objects.filter(
            organization=org, service=valid_service
        ).exists(), f"Missing subscription for {org.name}"

    # 5. No subscription for the unconfigured service
    assert not ServiceSubscription.objects.filter(
        service=unconfigured_service
    ).exists(), "Should not create subscriptions for unconfigured service"

    # 6. Pre-existing active subscription untouched
    active_sub = ServiceSubscription.objects.get(
        organization=pre_existing_active_org, service=valid_service
    )
    assert active_sub.is_active is True

    # 7. Pre-existing inactive subscription NOT re-activated
    inactive_sub.refresh_from_db()
    assert inactive_sub.is_active is False, (
        "Inactive subscription should not be re-activated"
    )

    # 8. Warning logged for missing OperatorServiceConfig
    warning_calls = [
        c
        for c in mock_logger.warning.call_args_list
        if "no OperatorServiceConfig exists" in str(c)
        and str(unconfigured_service.id) in str(c)
    ]
    assert warning_calls, "Expected warning about missing OperatorServiceConfig"

    # 9. No subscriptions for departement orgs
    for org in dept_orgs:
        assert not ServiceSubscription.objects.filter(
            organization=org, service=valid_service
        ).exists(), f"Unexpected subscription for departement org {org.name}"

    # -- Idempotency: re-run and check no duplicates --
    roles_before = OperatorOrganizationRole.objects.count()
    subs_before = ServiceSubscription.objects.count()

    result2 = import_dpnt_dataset.apply(
        kwargs={"force_update": True, "max_rows": 5}
    ).get()

    assert OperatorOrganizationRole.objects.count() == roles_before, (
        "Re-run should not duplicate roles"
    )
    assert ServiceSubscription.objects.count() == subs_before, (
        "Re-run should not duplicate subscriptions"
    )
    assert result2["auto_join"]["roles_created"] == 0
    assert result2["auto_join"]["subscriptions_created"] == 0
