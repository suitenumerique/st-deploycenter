"""
Unit tests for the User model
"""

from django.core.exceptions import ValidationError

import pytest

from core import factories

pytestmark = pytest.mark.django_db


class TestUserModel:
    """Test the User model."""

    def test_models_user_str(self):
        """The str representation should be the email."""
        user = factories.UserFactory()
        assert str(user) == user.email

    def test_models_user_id_unique(self):
        """The "id" field should be unique."""
        user = factories.UserFactory()
        with pytest.raises(ValidationError):
            factories.UserFactory(id=user.id)
