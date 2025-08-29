"""Fixtures for tests in the deploycenter core api application"""
# pylint: disable=redefined-outer-name

import pytest
from rest_framework.test import APIClient

from core import factories


@pytest.fixture
def other_user():
    """Create a user without mailbox access."""
    return factories.UserFactory()


# Add an api_client fixture
@pytest.fixture
def api_client():
    """Provide an instance of the API client for tests."""
    return APIClient()
