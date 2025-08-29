"""
Declare and configure the models for the deploycenter core application
"""
# pylint: disable=too-many-lines,too-many-instance-attributes

import uuid
from logging import getLogger

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models
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

    scope = models.JSONField(
        _("scope"),
        default=dict,
        blank=True,
        help_text=_("Geographic or population scope criteria for the operator"),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Whether this operator is currently active"),
    )

    class Meta:
        db_table = "deploycenter_operator"
        verbose_name = _("operator")
        verbose_name_plural = _("operators")
        ordering = ["name"]

    def __str__(self):
        return self.name


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
        unique=True,
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


class Service(BaseModel):
    """
    Service that can be subscribed to by organizations.
    Contains the base service configuration and metadata.
    """

    type = models.CharField(
        _("type"),
        max_length=100,
        help_text=_("Type of service (activates custom implementation code)"),
    )

    url = models.URLField(
        _("URL"),
        blank=True,
        null=True,
        help_text=_("URL where the service can be accessed"),
    )

    description = models.TextField(
        _("description"),
        blank=True,
        null=True,
        help_text=_("Description of what this service provides"),
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

    class Meta:
        db_table = "deploycenter_service"
        verbose_name = _("service")
        verbose_name_plural = _("services")
        ordering = ["type", "url"]
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.type} - {self.url or 'No URL'}"


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

    class Meta:
        db_table = "deploycenter_service_subscription"
        verbose_name = _("service subscription")
        verbose_name_plural = _("service subscriptions")
        unique_together = ["organization", "service"]
        ordering = ["organization__name", "service__type"]
        indexes = []

    def __str__(self):
        return f"{self.organization.name} → {self.service.type}"


class Metric(BaseModel):
    """
    Metrics that can be linked to services and optionally to organizations.
    Designed for aggregation and dashboard display.
    """

    # Metric identification
    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_("Name of the metric"),
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

    # Relationships - metrics are linked to service and optionally to organization
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
        help_text=_("Organization this metric is associated with (optional)"),
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "deploycenter_metric"
        verbose_name = _("metric")
        verbose_name_plural = _("metrics")
        ordering = ["-timestamp", "name"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["name"]),
            models.Index(fields=["service"]),
            models.Index(fields=["organization"]),
        ]

    def __str__(self):
        org_name = self.organization.name if self.organization else "Unknown"
        return f"{self.name}: {self.value} for {self.service.type} - {org_name}"

    def clean(self):
        """Ensure service relationship is set."""
        super().clean()
        if not self.service:
            raise ValidationError(_("Metric must be linked to a service"))
