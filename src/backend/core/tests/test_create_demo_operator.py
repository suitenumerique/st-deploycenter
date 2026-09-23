"""Tests for the create_demo_operator management command."""

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

import pytest

from core import factories
from core.models import Account, Operator, OperatorOrganizationRole, User

pytestmark = pytest.mark.django_db


@override_settings(ENVIRONMENT="production")
def test_create_demo_operator_refused_in_production():
    """The command writes nothing in production."""
    factories.OrganizationFactory.create_batch(10)

    with pytest.raises(CommandError, match="not allowed in production"):
        call_command("create_demo_operator", email="demo@example.com")

    assert not Operator.objects.exists()
    assert not OperatorOrganizationRole.objects.exists()
    assert not Account.objects.exists()


def test_create_demo_operator_outside_production():
    """Outside production, the command creates the demo operator and its user."""
    factories.OrganizationFactory.create_batch(10)

    call_command(
        "create_demo_operator", email="demo@example.com", operator_name="Demo X"
    )

    operator = Operator.objects.get(name="Demo X")
    assert OperatorOrganizationRole.objects.filter(operator=operator).count() == 10
    user = User.objects.get(email="demo@example.com")
    assert not user.has_usable_password()
