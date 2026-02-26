"""
Declare and configure the models for the deploycenter core application
"""
# pylint: disable=too-many-lines,too-many-instance-attributes,import-outside-toplevel,cyclic-import

import uuid
from enum import StrEnum
from logging import getLogger
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.utils.translation import gettext_lazy as _

from timezone_field import TimeZoneField

logger = getLogger(__name__)


class DuplicateEmailError(Exception):
    """Raised when an email is already associated with a pre-existing user."""

    def __init__(self, message=None, email=None):
        """Set message and email to describe the exception."""
        self.message = message
        self.email = email
        super().__init__(self.message)


class BaseModel(models.Model):
    """
    Serves as an abstract base model for other models, ensuring that records are validated
    before saving as Django doesn't do it by default.

    Includes fields common to all models: a UUID primary key and creation/update timestamps.
    """

    id = models.UUIDField(
        verbose_name=_("id"),
        help_text=_("primary key for the record as UUID"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        verbose_name=_("created on"),
        help_text=_("date and time at which a record was created"),
        auto_now_add=True,
        editable=False,
    )
    updated_at = models.DateTimeField(
        verbose_name=_("updated on"),
        help_text=_("date and time at which a record was last updated"),
        auto_now=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Call `full_clean` before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class UserManager(auth_models.UserManager):
    """Custom manager for User model with additional methods."""

    def get_user_by_sub_or_email(self, sub, email):
        """Fetch existing user by sub or email."""
        try:
            return self.get(sub=sub)
        except self.model.DoesNotExist as err:
            if not email:
                return None

            if settings.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION:
                try:
                    return self.get(email=email)
                except self.model.DoesNotExist:
                    pass
            elif (
                self.filter(email=email).exists()
                and not settings.OIDC_ALLOW_DUPLICATE_EMAILS
            ):
                raise DuplicateEmailError(
                    _(
                        "We couldn't find a user with this sub but the email is already "
                        "associated with a registered user."
                    )
                ) from err
        return None


class User(AbstractBaseUser, BaseModel, auth_models.PermissionsMixin):
    """User model to work with OIDC only authentication."""

    sub_validator = validators.RegexValidator(
        regex=r"^[\w.@+-:]+\Z",
        message=_(
            "Enter a valid sub. This value may contain only letters, "
            "numbers, and @/./+/-/_/: characters."
        ),
    )

    sub = models.CharField(
        _("sub"),
        help_text=_(
            "Required. 255 characters or fewer. Letters, numbers, and @/./+/-/_/: characters only."
        ),
        max_length=255,
        unique=True,
        validators=[sub_validator],
        blank=True,
        null=True,
    )

    full_name = models.CharField(_("full name"), max_length=255, null=True, blank=True)

    email = models.EmailField(_("identity email address"), blank=True, null=True)

    # Unlike the "email" field which stores the email coming from the OIDC token, this field
    # stores the email used by staff users to login to the admin site
    admin_email = models.EmailField(
        _("admin email address"), unique=True, blank=True, null=True
    )

    language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        verbose_name=_("language"),
        help_text=_("The language in which the user wants to see the interface."),
    )
    timezone = TimeZoneField(
        choices_display="WITH_GMT_OFFSET",
        use_pytz=False,
        default=settings.TIME_ZONE,
        help_text=_("The timezone in which the user wants to see times."),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )

    # Relationships
    operators = models.ManyToManyField(
        "Operator",
        through="UserOperatorRole",
        related_name="users",
        verbose_name=_("operators"),
        help_text=_("Operators this user has access to"),
    )

    objects = UserManager()

    USERNAME_FIELD = "admin_email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "deploycenter_user"
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email or self.admin_email or str(self.id)

    def save(self, *args, **kwargs):
        """Enforce validation before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class Operator(BaseModel):
    """
    Operator model representing meta-organizations that manage organizations.
    """

    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_("Name of the operator organization"),
    )

    url = models.URLField(
        _("homepage"),
        blank=True,
        null=True,
        help_text=_("Homepage URL of the operator"),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Whether this operator is currently active"),
    )

    config = models.JSONField(
        _("configuration"),
        default=dict,
        blank=True,
        null=True,
        help_text=_("Custom configuration data"),
    )

    class Meta:
        db_table = "deploycenter_operator"
        verbose_name = _("operator")
        verbose_name_plural = _("operators")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def compute_contribution(self):
        """Compute the financial contribution of the operator."""

        # Get all the communes & epcis managed by the operator.
        # Other types don't influence the contribution.
        all_communes = Organization.objects.filter(operators=self, type="commune")
        all_epcis = Organization.objects.filter(operators=self, type="epci")
        all_communes_in_epcis = Organization.objects.filter(type="commune").filter(
            epci_siren__in=all_epcis.values_list("siren", flat=True)
        )

        communes_in_scope = all_communes.union(all_communes_in_epcis)

        communes_in_scope_above_threshold = Organization.objects.filter(
            type="commune", pk__in=communes_in_scope.values_list("pk", flat=True)
        ).filter(population__gt=settings.OPERATOR_CONTRIBUTION_POPULATION_THRESHOLD)

        population_communes = (
            communes_in_scope_above_threshold.aggregate(
                total_population=models.Sum("population")
            )["total_population"]
            or 0
        )

        # Compute the financial contribution of the operator
        base_contribution = (
            population_communes * settings.OPERATOR_CONTRIBUTION_PER_POPULATION
        )

        # Ensure the contribution is not greater than the maximum base
        if base_contribution > settings.OPERATOR_CONTRIBUTION_MAXIMUM_BASE:
            contribution = settings.OPERATOR_CONTRIBUTION_MAXIMUM_BASE
        else:
            contribution = base_contribution

        # TODO: add usage-based contribution
        return {
            "base_contribution": base_contribution,
            "usage_contribution": {"2025-01": 0},
            "all_communes": all_communes.count(),
            "all_epcis": all_epcis.count(),
            "all_communes_in_epcis": all_communes_in_epcis.count(),
            "communes_in_scope": communes_in_scope.count(),
            "communes_in_scope_above_threshold": communes_in_scope_above_threshold.count(),
            "population": population_communes,
            "contribution": contribution,
        }


class UserOperatorRole(BaseModel):
    """
    RBAC relationship between User and Operator with role assignment.
    """

    ROLE_CHOICES = [
        ("admin", _("Administrator")),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="operator_roles",
        verbose_name=_("user"),
        help_text=_("User assigned to this operator"),
    )

    operator = models.ForeignKey(
        Operator,
        on_delete=models.CASCADE,
        related_name="user_roles",
        verbose_name=_("operator"),
        help_text=_("Operator this user has access to"),
    )

    role = models.CharField(
        _("role"),
        max_length=50,
        choices=ROLE_CHOICES,
        default="admin",
        help_text=_("Role assigned to the user for this operator"),
    )

    class Meta:
        db_table = "deploycenter_user_operator_role"
        verbose_name = _("user operator role")
        verbose_name_plural = _("user operator roles")
        unique_together = ["user", "operator"]
        ordering = ["user__full_name", "operator__name"]

    def __str__(self):
        return f"{self.user.full_name or self.user.email} - {self.operator.name} ({self.role})"


class Organization(BaseModel):
    """
    Organization model representing collectivités (local authorities) from the DPNT dataset.
    Based on data.gouv.fr structure.
    """

    class MailDomainStatus(StrEnum):
        """
        Status of the mail domain for the organization.
        """

        VALID = "valid"
        NEED_EMAIL_SETUP = "need_email_setup"
        INVALID = "invalid"

    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_("Official name of the collectivité"),
    )

    type = models.CharField(
        _("type"),
        max_length=50,
        default="commune",
        help_text=_("Type of collectivité (commune, epci, departement, region)"),
    )

    # Administrative codes
    siret = models.CharField(
        _("SIRET"),
        max_length=14,
        blank=True,
        null=True,
        help_text=_("SIRET code of the main establishment"),
        unique=True,
    )

    siren = models.CharField(
        _("SIREN"),
        max_length=9,
        blank=True,
        null=True,
        help_text=_("SIREN code of the organization"),
    )

    code_postal = models.CharField(
        _("postal code"),
        max_length=10,
        blank=True,
        null=True,
        help_text=_("Postal code of the collectivité"),
    )

    code_insee = models.CharField(
        _("INSEE code"),
        max_length=10,
        blank=True,
        null=True,
        help_text=_("INSEE administrative code"),
    )

    # Population data
    population = models.IntegerField(
        _("population"),
        blank=True,
        null=True,
        help_text=_("Population count from latest INSEE data"),
    )

    # EPCI information (for communes)
    epci_libelle = models.CharField(
        _("EPCI name"),
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Name of the EPCI the commune belongs to"),
    )

    epci_siren = models.CharField(
        _("EPCI SIREN"),
        max_length=9,
        blank=True,
        null=True,
        help_text=_("SIREN code of the EPCI"),
    )

    epci_population = models.IntegerField(
        _("EPCI population"),
        blank=True,
        null=True,
        help_text=_("Population of the EPCI"),
    )

    # Department and Region codes
    departement_code_insee = models.CharField(
        _("department code INSEE"),
        max_length=3,
        blank=True,
        null=True,
        help_text=_("INSEE department code"),
    )

    region_code_insee = models.CharField(
        _("region code INSEE"),
        max_length=2,
        blank=True,
        null=True,
        help_text=_("INSEE region code"),
    )

    # Digital presence indicators
    adresse_messagerie = models.EmailField(
        _("email address"),
        blank=True,
        null=True,
        help_text=_("Official email address from Service-Public.fr"),
    )

    site_internet = models.URLField(
        _("website"),
        blank=True,
        null=True,
        help_text=_("Official website URL from Service-Public.fr"),
    )

    telephone = models.CharField(
        _("phone"),
        max_length=20,
        blank=True,
        null=True,
        help_text=_("Official phone number from Service-Public.fr"),
    )

    # RPNT compliance
    rpnt = models.JSONField(
        _("RPNT criteria"),
        blank=True,
        null=True,
        default=list,
        help_text=_("List of valid RPNT criteria and meta-criteria"),
    )

    service_public_url = models.URLField(
        _("Service-Public URL"),
        blank=True,
        null=True,
        help_text=_("URL of the associated page on Service-Public.fr"),
    )

    # Relationships
    operators = models.ManyToManyField(
        Operator,
        through="OperatorOrganizationRole",
        related_name="organizations",
        verbose_name=_("operators"),
        help_text=_("Operators managing this organization"),
    )

    class Meta:
        db_table = "deploycenter_organization"
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["type"]),
            models.Index(fields=["code_insee"]),
            models.Index(fields=["siren"]),
            models.Index(fields=["siret"]),
            models.Index(fields=["departement_code_insee"]),
            models.Index(fields=["region_code_insee"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.type})"

    @property
    def adresse_messagerie_domain(self):
        """Get the mail domain for the organization."""
        if not self.adresse_messagerie:
            return None
        return self.adresse_messagerie.split("@")[1]

    @property
    def site_internet_domain(self):
        """
        Get the website domain for the organization.

        Not sure that this method is completely exhaustive.
        """
        if not self.site_internet:
            return None
        parsed = urlparse(self.site_internet)
        domain = parsed.netloc
        # Remove port number if present (e.g., "example.com:8080" -> "example.com")
        if ":" in domain:
            domain = domain.split(":")[0]
        # Remove www. prefix if present
        if domain.startswith("www."):
            return domain[4:]
        return domain

    @property
    def mail_domain(self):
        """Get the mail domain for the organization."""
        mail_domain, _ = self.get_mail_domain_status()
        return mail_domain

    def get_mail_domain_status(self):
        """
        Get the mail domain and its status based on RPNT validation.

        Returns:
            tuple: (mail_domain, status) where:
                - mail_domain: The mail domain to use (str or None)
                - status: MailDomainStatus enum value
        """

        if self.type == "other":
            # type=other orgs are not in scope of RPNT
            if self.adresse_messagerie_domain:
                return (self.adresse_messagerie_domain, self.MailDomainStatus.VALID)
            if self.site_internet_domain:
                return (
                    self.site_internet_domain,
                    self.MailDomainStatus.NEED_EMAIL_SETUP,
                )
            return (None, self.MailDomainStatus.INVALID)

        if not self.rpnt:
            return (None, self.MailDomainStatus.INVALID)

        rpnt_set = set(self.rpnt)

        website_valid = {"1.1"}
        email_valid = {"2.1", "2.2"}

        # Email domain is valid
        if email_valid.issubset(rpnt_set) and self.adresse_messagerie_domain:
            return (self.adresse_messagerie_domain, self.MailDomainStatus.VALID)

        # Website domain is valid.
        if website_valid.issubset(rpnt_set) and self.site_internet_domain:
            # Email domain is invalid or does not match the website domain.
            # Set the email domain to the website domain as it should be anyway once
            # it will be valid.
            return (self.site_internet_domain, self.MailDomainStatus.NEED_EMAIL_SETUP)

        # Website domain is invalid.
        return (None, self.MailDomainStatus.INVALID)


class OperatorOrganizationRole(BaseModel):
    """
    Through model representing the role of an operator within an organization.
    """

    operator = models.ForeignKey(
        Operator,
        on_delete=models.CASCADE,
        related_name="organization_roles",
        verbose_name=_("operator"),
        help_text=_("Operator with a role in the organization"),
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="operator_roles",
        verbose_name=_("organization"),
        help_text=_("Organization where the operator has a role"),
    )

    role = models.CharField(
        _("role"),
        max_length=50,
        choices=[("admin", _("Admin"))],
        default="admin",
        help_text=_("Role of the operator in the organization"),
    )

    class Meta:
        db_table = "deploycenter_operator_organization_role"
        verbose_name = _("operator organization role")
        verbose_name_plural = _("operator organization roles")
        unique_together = ["operator", "organization"]
        ordering = ["operator__name", "organization__name"]
        indexes = [
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return f"{self.operator.name} - {self.role} at {self.organization.name}"


class OperatorServiceConfig(BaseModel):
    """
    Through model representing a relationship between an operator and a service.
    """

    operator = models.ForeignKey(
        Operator,
        on_delete=models.CASCADE,
        verbose_name=_("operator"),
        help_text=_("Operator with a service configuration"),
    )
    service = models.ForeignKey(
        "Service",
        on_delete=models.CASCADE,
        verbose_name=_("service"),
        help_text=_("Service with a configuration"),
    )
    display_priority = models.IntegerField(
        _("display priority"),
        default=0,
        help_text=_("Priority of the operator and service for display"),
    )
    externally_managed = models.BooleanField(
        _("externally managed"),
        default=False,
        help_text=_(
            "Whether the subscriptions to this service are managed in the operator's own system"
        ),
    )

    class Meta:
        db_table = "deploycenter_operator_service_config"
        verbose_name = _("operator service config")
        verbose_name_plural = _("operator service configs")
        ordering = ["operator__name", "service__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "service"], name="unique_operator_service"
            )
        ]

    def __str__(self):
        return f"{self.operator.name} - {self.service.name} (priority: {self.display_priority})"


class Service(BaseModel):
    """
    Service that can be subscribed to by organizations.
    Contains the base service configuration and metadata.
    """

    id = models.AutoField(
        verbose_name="id",
        help_text=_("primary key for the record as numeric ID"),
        primary_key=True,
        editable=False,
    )

    type = models.CharField(
        _("type"),
        max_length=100,
        help_text=_("Type of service (activates custom implementation code)"),
    )

    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_("Human-readable name of the service"),
    )

    instance_name = models.CharField(
        _("instance name"),
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Name of the instance of the service"),
    )

    url = models.URLField(
        _("URL"),
        help_text=_("URL where the service can be accessed"),
    )

    description = models.TextField(
        _("description"),
        blank=True,
        null=True,
        help_text=_("Description of what this service provides"),
    )

    maturity = models.CharField(
        _("maturity"),
        max_length=10,
        choices=[
            ("alpha", "Alpha"),
            ("beta", "Beta"),
            ("stable", "Stable"),
            ("deprecated", "Deprecated"),
        ],
        default="alpha",
        help_text=_("Maturity level of the service"),
    )

    launch_date = models.DateField(
        _("launch date"),
        blank=True,
        null=True,
        help_text=_("Date of the launch of the service (out of beta)"),
    )

    # Base configuration for metrics scraping
    config = models.JSONField(
        _("configuration"),
        default=dict,
        blank=True,
        null=True,
        help_text=_(
            "Base configuration data for metrics scraping and service operation"
        ),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Whether this service is currently available for subscription"),
    )

    logo_svg = models.BinaryField(
        _("logo SVG"),
        blank=True,
        null=True,
        help_text=_("SVG logo for the service stored as binary data"),
    )

    operators = models.ManyToManyField(
        Operator,
        through="OperatorServiceConfig",
        related_name="services",
        verbose_name=_("operators"),
        help_text=_("Operators with a configuration for this service"),
    )

    required_services = models.ManyToManyField(
        "self",
        related_name="required_by",
        verbose_name=_("required services"),
        help_text=_("Services that are required for this service to be activated"),
        symmetrical=False,
        blank=True,
    )

    class Meta:
        db_table = "deploycenter_service"
        verbose_name = _("service")
        verbose_name_plural = _("services")
        ordering = ["name", "type", "url", "created_at"]
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.instance_name})"

    def get_logo_url(self):
        """
        Get the URL of the service logo as SVG.
        """
        if self.logo_svg:
            return f"{settings.API_PUBLIC_URL}servicelogo/{self.id}/"
        return None

    def can_activate(self, organization: Organization, operator: "Operator" = None):
        """
        Check if the service can be activated for the given organization.

        Returns:
            tuple: (can_activate: bool, reason: str | None)
        """
        # Check required services first
        required_services_count = self.required_services.count()
        if required_services_count:
            subscribed_required_count = (
                self.required_services.all()
                .filter(
                    subscriptions__organization=organization,
                    subscriptions__is_active=True,
                )
                .distinct()
                .count()
            )
            if subscribed_required_count < required_services_count:
                return (False, "missing_required_services")

        # Check population limits
        population_limits = (self.config or {}).get("population_limits", {})
        if not population_limits:
            return (True, None)

        # Check if operator can bypass population limits
        if operator and (operator.config or {}).get(
            "can_bypass_population_limits", False
        ):
            return (True, None)

        # Check population limits based on organization type
        commune_limit = population_limits.get("commune")
        epci_limit = population_limits.get("epci")

        # For communes: check if commune population < limit OR epci population < limit
        if organization.type == "commune":
            commune_pop = organization.population
            epci_pop = organization.epci_population

            # Block if both populations are null
            if commune_pop is None and epci_pop is None:
                return (False, "population_limit_exceeded")

            # Check if at least one is below the limit
            commune_ok = (
                commune_limit is not None
                and commune_pop is not None
                and commune_pop < commune_limit
            )
            epci_ok = (
                epci_limit is not None
                and epci_pop is not None
                and epci_pop < epci_limit
            )

            if commune_ok or epci_ok:
                return (True, None)
            return (False, "population_limit_exceeded")

        # For EPCIs: check if epci population < limit
        if organization.type == "epci":
            if epci_limit is None:
                return (True, None)

            epci_pop = organization.population
            if epci_pop is None:
                return (False, "population_limit_exceeded")

            if epci_pop < epci_limit:
                return (True, None)
            return (False, "population_limit_exceeded")

        # For other types, allow activation if no specific limit is defined
        return (True, None)


class ServiceSubscription(BaseModel):
    """
    Through model representing a subscription between an organization and a service instance.
    Contains subscription-specific configuration and metadata.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="service_subscriptions",
        verbose_name=_("organization"),
        help_text=_("Organization subscribing to the service"),
    )

    operator = models.ForeignKey(
        Operator,
        on_delete=models.CASCADE,
        related_name="service_subscriptions",
        verbose_name=_("operator"),
        help_text=_("Operator managing the organization"),
    )

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        verbose_name=_("service"),
        help_text=_("Service being subscribed to"),
    )

    # Subscription metadata
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
        help_text=_("Additional metadata for this subscription"),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Whether this subscription is currently active"),
    )

    class Meta:
        db_table = "deploycenter_service_subscription"
        verbose_name = _("service subscription")
        verbose_name_plural = _("service subscriptions")
        unique_together = ["organization", "service"]
        ordering = ["organization__name", "service__name"]
        indexes = []

    def __str__(self):
        return f"{self.operator.name} → {self.organization.name} → {self.service.name}"

    def save(self, *args, **kwargs):
        """
        Save the service subscription.
        """
        super().save(*args, **kwargs)

        from core.services import get_service_handler  # noqa: PLC0415

        service_handler = get_service_handler(self.service)
        if service_handler:
            service_handler.create_default_entitlements(self)

    @property
    def idp_name(self):
        """
        Get the name of the IDP for the ProConnect subscription.
        """
        if not self.metadata.get("idp_id"):
            return None
        if not self.operator.config["idps"]:
            return None
        for idp in self.operator.config["idps"]:
            if idp["id"] == self.metadata.get("idp_id"):
                return idp["name"]
        return None

    def validate_proconnect_subscription(self):
        """
        When activating a ProConnect subscription, we need to validate
        that the mail domain and IDP are set.
        """
        if not self.is_active:
            return

        if self.service.type != "proconnect":
            return

        if not self.organization.mail_domain:
            raise ValidationError(
                "Mail domain is required for ProConnect subscription."
            )

        if not self.metadata.get("idp_id"):
            raise ValidationError("IDP is required for ProConnect subscription.")

    def validate_can_activate(self):
        """
        Validate that the organization can be activate with criteria like population limit.
        Only checks at activation time, not on every save.
        """
        if not self.is_active:
            return

        can_activate, reason = self.service.can_activate(
            self.organization, self.operator
        )
        if can_activate:
            return

        raise ValidationError(f"Cannot activate this subscription. Reason: {reason}")

    def clean(self):
        """
        Validate that when is_active is True, all required services have active subscriptions.
        """
        super().clean()
        self.validate_proconnect_subscription()
        self.validate_can_activate()


class AccountServiceLink(BaseModel):
    """
    Through model representing a link between an account and a service.
    """

    account = models.ForeignKey(
        "Account",
        on_delete=models.CASCADE,
        related_name="service_links",
        verbose_name=_("account"),
        help_text=_("Account this service link is associated with"),
    )

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="service_links",
        verbose_name=_("service"),
        help_text=_("Service this account is associated with"),
    )

    roles = models.JSONField(
        _("roles"),
        default=list,
        blank=True,
        help_text=_("Array of role strings for this account"),
    )

    class Meta:
        db_table = "deploycenter_account_service_link"
        verbose_name = _("account service link")
        verbose_name_plural = _("account service links")
        unique_together = ["account", "service"]
        indexes = [
            models.Index(fields=["account"]),
            models.Index(fields=["service"]),
        ]

    def __str__(self):
        return f"{self.account.email} - {self.service.name}"


class Account(BaseModel):
    """
    An account is an entity to which metrics are attached to.
    This entity is used as a reference to resolve entitlements.
    It can be a user, a mailbox, etc. It depends on the service's use case.
    """

    email = models.EmailField(
        _("email"),
        max_length=255,
        help_text=_("Email address of the account"),
        default="",
        blank=True,
    )

    external_id = models.CharField(
        _("external ID"),
        max_length=255,
        help_text=_("External ID of the account"),
        default="",
        blank=True,
    )

    type = models.CharField(
        _("account type"),
        max_length=50,
        help_text=_("Type of account"),
        default="",
        blank=True,
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="accounts",
        verbose_name=_("organization"),
        help_text=_("Organization this account is associated with"),
    )

    roles = models.JSONField(
        _("roles"),
        default=list,
        blank=True,
        help_text=_("Array of role strings for this account"),
    )

    class Meta:
        db_table = "deploycenter_account"
        verbose_name = _("account")
        verbose_name_plural = _("accounts")
        ordering = ["created_at", "organization__name", "type", "external_id"]
        indexes = [
            models.Index(fields=["organization"]),
            models.Index(fields=["type"]),
            models.Index(fields=["email"]),
            models.Index(fields=["external_id"]),
            # The query used in store_service_usage_metrics task.
            models.Index(fields=["external_id", "type", "organization"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["external_id", "type", "organization"],
                condition=~models.Q(external_id=""),
                name="unique_account_external_id_per_org_type",
            ),
            models.UniqueConstraint(
                fields=["email", "type", "organization"],
                condition=~models.Q(email=""),
                name="unique_account_email_per_org_type",
            ),
        ]

    def __str__(self):
        return f"{self.id} (external_id: {self.external_id}) - {self.type} - {self.email} - {self.organization.name}"

    @classmethod
    def find_by_identifiers(
        cls,
        organization,
        account_type,
        external_id="",
        email="",
        reconcile_external_id=False,
    ):
        """
        Find an account by external_id and/or email (fallback).
        If reconcile_external_id=True and found by email, backfills external_id
        (only for trusted sources).
        """
        account = None
        found_by = None
        filters = {"type": account_type, "organization": organization}

        if external_id:
            account = cls.objects.filter(external_id=external_id, **filters).first()
            if account:
                found_by = "external_id"

        if not account and email:
            account = cls.objects.filter(email=email, **filters).first()
            if account:
                found_by = "email"

        if account and found_by == "email" and reconcile_external_id:
            if external_id and not account.external_id:
                try:
                    account.external_id = external_id
                    account.save(update_fields=["external_id", "updated_at"])
                    logger.info(
                        "Reconciled external_id for account %s (org=%s, type=%s)",
                        account.id,
                        organization.id,
                        account_type,
                    )
                except IntegrityError:
                    logger.warning(
                        "Failed to reconcile external_id %s for account %s"
                        " - already exists",
                        external_id,
                        account.id,
                    )
                    account.refresh_from_db()

        return account


class Metric(models.Model):
    """
    Metrics that can be linked to services and to organizations.
    Designed for aggregation and dashboard display.
    """

    # Metric identification
    key = models.CharField(
        _("key"),
        max_length=255,
        help_text=_("Key identifier of the metric"),
    )

    value = models.DecimalField(
        _("value"),
        max_digits=20,
        decimal_places=6,
        help_text=_("Numeric value of the metric"),
    )

    # Timestamp for time-series data
    timestamp = models.DateTimeField(
        _("timestamp"),
        auto_now_add=True,
        help_text=_("When this metric was recorded"),
    )

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="metrics",
        verbose_name=_("service"),
        help_text=_("Service this metric is associated with"),
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="metrics",
        verbose_name=_("organization"),
        help_text=_("Organization this metric is associated with"),
    )

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="metrics",
        verbose_name=_("account"),
        help_text=_("Account this metric is associated with"),
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "deploycenter_metric"
        verbose_name = _("metric")
        verbose_name_plural = _("metrics")
        ordering = ["-timestamp", "key"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["key"]),
            models.Index(fields=["service"]),
            models.Index(fields=["organization"]),
            models.Index(fields=["account"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "organization", "account", "key"],
                name="unique_metric_with_account",
                # account ForeignKey can be null, so we need to consider NULL values as equal.
                # See https://www.postgresql.org/about/featurematrix/detail/unique-nulls-not-distinct/
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        org_name = self.organization.name if self.organization else "Unknown"
        account_info = ""
        if self.account:
            account_info = f" with account ({self.account})"
        return f"{self.key}: {self.value} for {self.service.name} - {org_name}{account_info}"


class Entitlement(BaseModel):
    """
    Entitlement model representing an entitlement for a service subscription.
    An entitlement is a way to constrain some service usage for an account.
    For example, a drive storage entitlement can be used to limit the storage
    space available to an account.
    """

    class EntitlementType(models.TextChoices):
        """
        Types of entitlements.
        """

        DRIVE_STORAGE = "drive_storage"
        MESSAGES_STORAGE = "messages_storage"

    service_subscription = models.ForeignKey(
        ServiceSubscription,
        on_delete=models.CASCADE,
        related_name="entitlements",
        verbose_name=_("service subscription"),
        help_text=_("Service subscription this entitlement is associated with"),
    )

    type = models.CharField(
        _("type"),
        max_length=50,
        help_text=_("Type of entitlement"),
    )

    config = models.JSONField(
        _("configuration"),
        default=dict,
        blank=True,
        null=True,
        help_text=_(
            "Base configuration data for metrics scraping and service operation"
        ),
    )

    account_type = models.CharField(
        _("account type"),
        max_length=50,
        help_text=_("Type of account"),
        default="",
        blank=True,
    )

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="entitlements",
        verbose_name=_("account"),
        help_text=_("Account this entitlement is associated with"),
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "deploycenter_entitlement"
        verbose_name = _("entitlement")
        verbose_name_plural = _("entitlements")
        unique_together = ["service_subscription", "type", "account_type", "account"]
        indexes = [
            models.Index(fields=["service_subscription"]),
        ]

    def __str__(self):
        account_id = self.account.id if self.account else None
        return (
            f"{self.service_subscription.organization.name} - "
            f"{self.type} - "
            f"{self.account_type} - "
            f"{account_id}"
        )

    def clean(self):
        """Validate that the type is a valid EntitlementType and account organization matches."""
        super().clean()
        if self.type and self.type not in self.EntitlementType.values:
            valid_types = ", ".join(self.EntitlementType.values)
            raise ValidationError(
                {
                    "type": _(
                        "Invalid entitlement type '%(type)s'. Valid types are: %(valid_types)s"
                    )
                    % {
                        "type": self.type,
                        "valid_types": valid_types,
                    }
                }
            )

        # Validate that account organization matches service_subscription organization
        if self.account is not None:
            if (
                self.service_subscription is not None
                and self.account.organization_id
                != self.service_subscription.organization_id
            ):
                raise ValidationError(
                    {
                        "account": _(
                            "The account's organization must match the service subscription's organization."
                        )
                    }
                )
            if self.account.type != self.account_type:
                raise ValidationError(
                    {
                        "account": _(
                            "The account's type must match the entitlement's account type."
                        )
                    }
                )
