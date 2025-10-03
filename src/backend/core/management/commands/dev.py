"""Drop all tables in the public schema of the PostgreSQL database."""

from core import factories
from core.models import Organization, Operator
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    """Dev debug stuff."""

    help = "Dev debug stuff."

    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument("operator_id", help="Operator ID to debug")

    def handle(self, *args, **options):
        """Dev debug stuff."""
        
        operator = Operator.objects.get(id=options["operator_id"])
        organizations = Organization.objects.filter(region_code_insee=28)
        for organization in organizations:
            factories.OperatorOrganizationRoleFactory(operator=operator, organization=organization, role="admin")
