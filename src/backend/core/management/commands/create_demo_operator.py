"""
Management command to create a demo operator with services, organizations, and metrics.

This command sets up a complete demo environment for testing purposes:
- Creates an operator and links it to a user
- Creates messages and drive services
- Links random organizations to the operator
- Generates accounts and metrics for each organization
"""

import random
import uuid
from decimal import Decimal
from logging import getLogger

from django.core.management.base import BaseCommand, CommandError

from core.models import (
    Account,
    Metric,
    Operator,
    OperatorOrganizationRole,
    OperatorServiceConfig,
    Organization,
    Service,
    User,
    UserOperatorRole,
)

logger = getLogger(__name__)

# Constants
ORGANIZATIONS_TO_LINK = 10
METRICS_PER_SERVICE = 200
METRIC_MIN_VALUE = 0
METRIC_MAX_VALUE = 10_000_000


def create_operator(name: str) -> Operator:
    """
    Create and return a new Operator.

    Args:
        name: The name for the new operator.

    Returns:
        The created Operator instance.
    """
    operator = Operator.objects.create(
        name=name,
        is_active=True,
    )
    logger.info("Created operator: %s", operator.name)
    return operator


def get_or_create_user(email: str) -> User:
    """
    Get or create a user with the given email.

    Args:
        email: The email address for the user.

    Returns:
        The User instance.
    """
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"full_name": f"Demo User ({email})"},
    )
    if created:
        logger.info("Created user: %s", email)
    else:
        logger.info("Found existing user: %s", email)
    return user


def create_user_operator_role(user: User, operator: Operator) -> UserOperatorRole:
    """
    Link a user to an operator with admin role.

    Args:
        user: The user to link.
        operator: The operator to link to.

    Returns:
        The created UserOperatorRole instance.
    """
    role = UserOperatorRole.objects.create(
        user=user,
        operator=operator,
        role="admin",
    )
    logger.info("Created user operator role: %s -> %s", user.email, operator.name)
    return role


def create_services(operator: Operator) -> tuple[Service, Service]:
    """
    Create messages and drive services and link them to the operator.

    Args:
        operator: The operator to link services to.

    Returns:
        A tuple of (messages_service, drive_service).
    """
    messages_service = Service.objects.create(
        type="messages",
        name=f"Messages ({operator.name})",
        instance_name=f"messages-{operator.name.lower().replace(' ', '-')}",
        url=f"https://messages.{operator.name.lower().replace(' ', '-')}.example.com",
        description="Demo messages service",
        is_active=True,
    )
    logger.info("Created messages service: %s", messages_service.name)

    drive_service = Service.objects.create(
        type="drive",
        name=f"Drive ({operator.name})",
        instance_name=f"drive-{operator.name.lower().replace(' ', '-')}",
        url=f"https://drive.{operator.name.lower().replace(' ', '-')}.example.com",
        description="Demo drive service",
        is_active=True,
    )
    logger.info("Created drive service: %s", drive_service.name)

    # Link services to operator via OperatorServiceConfig
    OperatorServiceConfig.objects.create(
        operator=operator,
        service=messages_service,
        display_priority=1,
    )
    OperatorServiceConfig.objects.create(
        operator=operator,
        service=drive_service,
        display_priority=2,
    )
    logger.info("Linked services to operator: %s", operator.name)

    return messages_service, drive_service


def link_organizations(operator: Operator, count: int) -> list[Organization]:
    """
    Randomly select and link organizations to the operator.

    Uses an efficient approach that avoids loading all organizations into memory:
    fetches only the PKs, samples from them, then fetches the selected records.

    Args:
        operator: The operator to link organizations to.
        count: Number of organizations to link.

    Returns:
        List of linked Organization instances.
    """
    # Only fetch PKs to minimize memory usage
    all_pks = list(Organization.objects.values_list("pk", flat=True))
    total_count = len(all_pks)

    if total_count < count:
        raise CommandError(
            f"Not enough organizations in database. Found {total_count}, need {count}."
        )

    # Sample random PKs and fetch only those organizations
    selected_pks = random.sample(all_pks, count)
    selected_organizations = list(Organization.objects.filter(pk__in=selected_pks))

    for organization in selected_organizations:
        OperatorOrganizationRole.objects.create(
            operator=operator,
            organization=organization,
            role="admin",
        )
        logger.info("Linked organization: %s -> %s", organization.name, operator.name)

    return selected_organizations


def generate_random_email() -> str:
    """Generate a random email address."""
    random_id = uuid.uuid4().hex[:8]
    return f"user-{random_id}@demo.example.com"


def generate_random_external_id() -> str:
    """Generate a random external ID."""
    return uuid.uuid4().hex


def generate_random_metric_value() -> Decimal:
    """Generate a random metric value between 0 and 10 million."""
    return Decimal(random.randint(METRIC_MIN_VALUE, METRIC_MAX_VALUE))


def create_accounts_and_metrics(
    organization: Organization,
    service: Service,
    account_type: str,
    count: int,
    include_email: bool,
) -> tuple[list[Account], list[Metric]]:
    """
    Create accounts and metrics for an organization and service.

    Args:
        organization: The organization to create accounts for.
        service: The service to create metrics for.
        account_type: The type of account ("user" or "mailbox").
        count: Number of accounts and metrics to create.
        include_email: Whether to include email in accounts.

    Returns:
        A tuple of (accounts_list, metrics_list).
    """
    accounts = []
    metrics = []

    for _ in range(count):
        email = generate_random_email() if include_email else ""
        external_id = generate_random_external_id()

        account = Account(
            email=email,
            external_id=external_id,
            type=account_type,
            organization=organization,
        )
        accounts.append(account)

    # Bulk create accounts
    Account.objects.bulk_create(accounts)
    logger.info(
        "Created %d accounts (type=%s) for organization: %s",
        len(accounts),
        account_type,
        organization.name,
    )

    # Create metrics for each account
    for account in accounts:
        metric = Metric(
            key="storage_used",
            value=generate_random_metric_value(),
            service=service,
            organization=organization,
            account=account,
        )
        metrics.append(metric)

    # Bulk create metrics
    Metric.objects.bulk_create(metrics)
    logger.info(
        "Created %d metrics for service %s, organization: %s",
        len(metrics),
        service.name,
        organization.name,
    )

    return accounts, metrics


class Command(BaseCommand):
    """Management command to create a demo operator with full setup."""

    help = """
    Create a demo operator with services, organizations, and metrics.
    
    This command sets up:
    - A new operator linked to the specified user
    - Messages and Drive services
    - 10 randomly selected organizations linked to the operator
    - 200 accounts and metrics per organization per service
    
    Example:
        python manage.py create_demo_operator --email admin@example.com
    """

    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument(
            "--email",
            required=True,
            help="Email address for the user to link to the operator",
        )
        parser.add_argument(
            "--operator-name",
            default=None,
            help="Name for the operator (defaults to 'Demo Operator <random>')",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        email = options["email"]
        operator_name = options["operator_name"] or f"Demo Operator {uuid.uuid4().hex[:6]}"

        self.stdout.write(f"Creating demo operator: {operator_name}")
        self.stdout.write(f"User email: {email}")
        self.stdout.write("")

        # Step 1: Create operator
        self.stdout.write("Step 1: Creating operator...")
        operator = create_operator(operator_name)
        self.stdout.write(self.style.SUCCESS(f"  Created operator: {operator.name}"))

        # Step 2: Get or create user and link to operator
        self.stdout.write("Step 2: Setting up user and role...")
        user = get_or_create_user(email)
        create_user_operator_role(user, operator)
        self.stdout.write(self.style.SUCCESS(f"  Linked user {email} to operator"))

        # Step 3: Create services
        self.stdout.write("Step 3: Creating services...")
        messages_service, drive_service = create_services(operator)
        self.stdout.write(self.style.SUCCESS(f"  Created messages service: {messages_service.name}"))
        self.stdout.write(self.style.SUCCESS(f"  Created drive service: {drive_service.name}"))

        # Step 4: Link organizations
        self.stdout.write(f"Step 4: Linking {ORGANIZATIONS_TO_LINK} organizations...")
        try:
            organizations = link_organizations(operator, ORGANIZATIONS_TO_LINK)
            self.stdout.write(
                self.style.SUCCESS(f"  Linked {len(organizations)} organizations")
            )
        except CommandError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            raise

        # Step 5: Create accounts and metrics for each organization
        self.stdout.write("Step 5: Creating accounts and metrics...")
        total_accounts = 0
        total_metrics = 0

        for organization in organizations:
            self.stdout.write(f"  Processing organization: {organization.name}")

            # Drive service: accounts with type "user" (with email and external_id)
            drive_accounts, drive_metrics = create_accounts_and_metrics(
                organization=organization,
                service=drive_service,
                account_type="user",
                count=METRICS_PER_SERVICE,
                include_email=True,
            )
            total_accounts += len(drive_accounts)
            total_metrics += len(drive_metrics)

            # Messages service: accounts with type "mailbox" (no email, only external_id)
            messages_accounts, messages_metrics = create_accounts_and_metrics(
                organization=organization,
                service=messages_service,
                account_type="mailbox",
                count=METRICS_PER_SERVICE,
                include_email=False,
            )
            total_accounts += len(messages_accounts)
            total_metrics += len(messages_metrics)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo operator created successfully!"))
        self.stdout.write(self.style.SUCCESS(f"  Operator: {operator.name} (ID: {operator.id})"))
        self.stdout.write(self.style.SUCCESS(f"  User: {email}"))
        self.stdout.write(self.style.SUCCESS(f"  Services: {messages_service.name}, {drive_service.name}"))
        self.stdout.write(self.style.SUCCESS(f"  Organizations linked: {len(organizations)}"))
        self.stdout.write(self.style.SUCCESS(f"  Total accounts created: {total_accounts}"))
        self.stdout.write(self.style.SUCCESS(f"  Total metrics created: {total_metrics}"))
