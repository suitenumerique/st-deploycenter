"""
Test account reconciliation: find_by_identifiers, constraints, and trusted binding.
"""

from django.core.exceptions import ValidationError

import pytest

from core import factories, models

pytestmark = pytest.mark.django_db


@pytest.fixture(name="org")
def fixture_org():
    """Create a test organization."""
    return factories.OrganizationFactory()


# --- find_by_identifiers ---


def test_find_by_external_id(org):
    """Basic lookup by external_id."""
    account = factories.AccountFactory(
        organization=org, external_id="ext-1", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org, account_type="user", external_id="ext-1"
    )
    assert found is not None
    assert found.id == account.id


def test_find_by_email_fallback(org):
    """When external_id not found, falls back to email."""
    account = factories.AccountFactory(
        organization=org, external_id="", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org,
        account_type="user",
        external_id="unknown-ext",
        email="a@test.com",
    )
    assert found is not None
    assert found.id == account.id


def test_find_no_match(org):
    """Returns None when no match at all."""
    factories.AccountFactory(
        organization=org, external_id="ext-1", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org, account_type="user", external_id="nope", email="nope@test.com"
    )
    assert found is None


def test_find_respects_type(org):
    """Lookup must match account type."""
    factories.AccountFactory(
        organization=org, external_id="ext-1", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org, account_type="mailbox", external_id="ext-1"
    )
    assert found is None


def test_find_does_not_backfill_external_id_untrusted(org):
    """When reconcile_external_id=False (untrusted), external_id is NOT backfilled."""
    account = factories.AccountFactory(
        organization=org, external_id="", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org,
        account_type="user",
        external_id="new-ext",
        email="a@test.com",
        reconcile_external_id=False,
    )
    assert found is not None
    assert found.id == account.id
    # external_id should NOT have been set
    account.refresh_from_db()
    assert account.external_id == ""


def test_find_backfills_external_id_trusted(org):
    """When reconcile_external_id=True (trusted), external_id IS backfilled."""
    account = factories.AccountFactory(
        organization=org, external_id="", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org,
        account_type="user",
        external_id="new-ext",
        email="a@test.com",
        reconcile_external_id=True,
    )
    assert found is not None
    assert found.id == account.id
    account.refresh_from_db()
    assert account.external_id == "new-ext"


def test_find_does_not_overwrite_existing_external_id_trusted(org):
    """Even trusted sources cannot overwrite an existing external_id."""
    account = factories.AccountFactory(
        organization=org, external_id="original-ext", email="a@test.com", type="user"
    )
    found = models.Account.find_by_identifiers(
        organization=org,
        account_type="user",
        external_id="different-ext",
        email="a@test.com",
        reconcile_external_id=True,
    )
    # Should find by email (since "different-ext" doesn't match "original-ext")
    assert found is not None
    assert found.id == account.id
    account.refresh_from_db()
    # external_id is NOT overwritten because it's already set
    assert account.external_id == "original-ext"


# --- Constraints ---


def test_constraint_allows_multiple_blank_external_id(org):
    """Multiple accounts with blank external_id are allowed (different emails)."""
    models.Account.objects.create(
        organization=org, external_id="", email="a@test.com", type="user"
    )
    models.Account.objects.create(
        organization=org, external_id="", email="b@test.com", type="user"
    )
    assert models.Account.objects.filter(organization=org).count() == 2


def test_constraint_unique_external_id_per_type_org(org):
    """Cannot create two accounts with same non-blank external_id+type+org."""
    models.Account.objects.create(
        organization=org, external_id="ext-1", email="a@test.com", type="user"
    )
    with pytest.raises(ValidationError):
        models.Account.objects.create(
            organization=org, external_id="ext-1", email="b@test.com", type="user"
        )


def test_constraint_unique_email_per_type_org(org):
    """Cannot create two accounts with same non-blank email+type+org."""
    models.Account.objects.create(
        organization=org, external_id="ext-1", email="a@test.com", type="user"
    )
    with pytest.raises(ValidationError):
        models.Account.objects.create(
            organization=org, external_id="ext-2", email="a@test.com", type="user"
        )


def test_constraint_allows_same_email_different_type(org):
    """Same email is allowed with different account types."""
    models.Account.objects.create(
        organization=org, external_id="", email="a@test.com", type="user"
    )
    models.Account.objects.create(
        organization=org, external_id="", email="a@test.com", type="mailbox"
    )
    assert models.Account.objects.filter(organization=org).count() == 2


def test_constraint_allows_multiple_blank_email(org):
    """Multiple accounts with blank email are allowed (different external_ids)."""
    models.Account.objects.create(
        organization=org, external_id="ext-1", email="", type="user"
    )
    models.Account.objects.create(
        organization=org, external_id="ext-2", email="", type="user"
    )
    assert models.Account.objects.filter(organization=org).count() == 2
