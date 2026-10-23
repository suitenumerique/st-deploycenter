"""Tests for the migration that drops the old ``out_of_sync`` service flag."""

from importlib import import_module

from django.apps import apps

import pytest

from core import factories

pytestmark = pytest.mark.django_db

migration = import_module("core.migrations.0022_remove_service_out_of_sync")


def test_remove_out_of_sync_drops_only_that_key():
    """The flag goes, the rest of the config stays."""
    flagged = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "an-idp", "out_of_sync": True}
    )
    clean = factories.ServiceFactory(type="proconnect", config={"idp_id": "other"})
    empty = factories.ServiceFactory(config={})

    migration.remove_out_of_sync(apps, None)

    flagged.refresh_from_db()
    clean.refresh_from_db()
    empty.refresh_from_db()
    assert flagged.config == {"idp_id": "an-idp"}
    assert clean.config == {"idp_id": "other"}
    assert empty.config == {}
