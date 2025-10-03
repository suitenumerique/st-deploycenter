"""Admin classes and registrations for core app."""

from django import forms
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _

from . import models


class ServiceForm(forms.ModelForm):
    """Custom form for Service model with file upload for logo_svg."""

    logo_svg_file = forms.FileField(
        label=_("Logo SVG File"),
        help_text=_("Upload an SVG file for the service logo"),
        required=False,
        widget=forms.FileInput(attrs={"accept": ".svg"}),
    )

    class Meta:
        model = models.Service
        fields = [
            "name",
            "type",
            "url",
            "description",
            "maturity",
            "launch_date",
            "is_active",
            "logo_svg_file",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.logo_svg:
            self.fields["logo_svg_file"].help_text = _(
                "Current logo is set. Upload a new file to replace it."
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        logo_file = self.cleaned_data.get("logo_svg_file")
        if logo_file:
            # Read the uploaded file and store as binary data
            instance.logo_svg = logo_file.read()
        if commit:
            instance.save()
        return instance


class OperatorUsersInline(admin.TabularInline):
    """Inline admin for users associated with an operator."""

    model = models.UserOperatorRole
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ["user"]
    fields = ("user", "role", "created_at", "updated_at")
    verbose_name = _("user role")
    verbose_name_plural = _("user roles")


class OrganizationServicesInline(admin.TabularInline):
    """Inline admin for service subscriptions in an organization."""

    model = models.ServiceSubscription
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ["service"]
    fields = ("service", "metadata", "created_at", "updated_at")
    verbose_name = _("service subscription")
    verbose_name_plural = _("service subscriptions")
    list_select_related = ["service"]


@admin.register(models.User)
class UserAdmin(auth_admin.UserAdmin):
    """Admin class for the User model"""

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "admin_email",
                    "password",
                )
            },
        ),
        (
            _("Personal info"),
            {
                "fields": (
                    "sub",
                    "email",
                    "full_name",
                    "language",
                    "timezone",
                )
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )
    list_display = (
        "id",
        "sub",
        "full_name",
        "admin_email",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_staff", "is_superuser", "is_active")
    ordering = (
        "is_active",
        "-is_superuser",
        "-is_staff",
        "-updated_at",
        "full_name",
    )
    readonly_fields = (
        "id",
        "sub",
        "email",
        "created_at",
        "updated_at",
    )
    search_fields = ("id", "sub", "admin_email", "email", "full_name")
    autocomplete_fields = []


@admin.register(models.Operator)
class OperatorAdmin(admin.ModelAdmin):
    """Admin class for the Operator model"""

    list_display = ("name", "url", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "url")
    ordering = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("name", "url", "is_active")}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )
    autocomplete_fields = ["users"]
    inlines = [OperatorUsersInline]


@admin.register(models.UserOperatorRole)
class UserOperatorRoleAdmin(admin.ModelAdmin):
    """Admin class for the UserOperatorRole model"""

    list_display = ("user", "operator", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("user__full_name", "user__email", "operator__name")
    ordering = ("user__full_name", "operator__name")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ["user", "operator"]
    list_select_related = ["user", "operator"]


@admin.register(models.Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin class for the Organization model"""

    list_display = (
        "name",
        "type",
        "code_insee",
        "siren",
        "population",
        "created_at",
    )
    list_filter = (
        "type",
        "departement_code_insee",
        "region_code_insee",
        "created_at",
    )
    search_fields = (
        "name",
        "code_insee",
        "siren",
        "code_postal",
        "epci_libelle",
        "adresse_messagerie",
    )
    ordering = ("name", "type")
    readonly_fields = ("id", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("name", "type")}),
        (
            _("Administrative Information"),
            {
                "fields": (
                    "siret",
                    "siren",
                    "code_postal",
                    "code_insee",
                    "departement_code_insee",
                    "region_code_insee",
                    "epci_libelle",
                    "epci_siren",
                )
            },
        ),
        (
            _("Population Data"),
            {"fields": ("population", "epci_population")},
        ),
        (
            _("Digital Presence"),
            {
                "fields": (
                    "adresse_messagerie",
                    "site_internet",
                    "telephone",
                    "rpnt",
                    "service_public_url",
                )
            },
        ),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )
    inlines = [OrganizationServicesInline]


@admin.register(models.Service)
class ServiceAdmin(admin.ModelAdmin):
    """Admin class for the Service model"""

    form = ServiceForm
    list_display = ("name", "type", "url", "description", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "type", "description")
    ordering = ("name", "type", "url")
    readonly_fields = ("id", "created_at", "updated_at")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "type",
                    "url",
                    "description",
                    "maturity",
                    "launch_date",
                    "is_active",
                )
            },
        ),
        (_("Logo"), {"fields": ("logo_svg_file",)}),
        (_("Configuration"), {"fields": ("config",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(models.OperatorOrganizationRole)
class OperatorOrganizationRoleAdmin(admin.ModelAdmin):
    """Admin class for the OperatorOrganizationRole model"""

    list_display = ("operator", "organization", "role", "created_at")
    list_filter = ("role", "operator", "organization__type", "created_at")
    search_fields = ("operator__name", "organization__name")
    ordering = ("operator__name", "organization__name")
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["operator", "organization"]

    fieldsets = (
        (None, {"fields": ("operator", "organization", "role")}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(models.OperatorServiceConfig)
class OperatorServiceConfigAdmin(admin.ModelAdmin):
    """Admin class for the OperatorServiceConfig model"""

    list_display = ("operator", "service", "display_priority", "created_at")
    list_filter = ("operator", "service__is_active", "created_at")
    search_fields = ("operator__name", "service__name", "service__type")
    ordering = ("operator__name", "display_priority", "service__name")
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["operator", "service"]

    fieldsets = (
        (None, {"fields": ("operator", "service", "display_priority")}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(models.ServiceSubscription)
class ServiceSubscriptionAdmin(admin.ModelAdmin):
    """Admin class for the ServiceSubscription model"""

    list_display = ("organization", "service", "created_at")
    list_filter = ("organization__operator_roles__operator", "created_at")
    search_fields = ("organization__name", "service__name", "service__type")
    ordering = ("organization__name", "service__name")
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["organization", "service"]

    fieldsets = (
        (None, {"fields": ("organization", "service")}),
        (_("Subscription Data"), {"fields": ("metadata",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(models.Metric)
class MetricAdmin(admin.ModelAdmin):
    """Admin class for the Metric model"""

    list_display = ("key", "value", "service", "organization", "timestamp")
    list_filter = ("timestamp", "organization__operator_roles__operator")
    search_fields = ("key", "organization__name", "service__name", "service__type")
    ordering = ("-timestamp", "key")
    readonly_fields = ("id", "timestamp")

    autocomplete_fields = ["service", "organization"]

    fieldsets = (
        (None, {"fields": ("key", "value")}),
        (_("Relationships"), {"fields": ("service", "organization")}),
        (_("Metadata"), {"fields": ("timestamp",)}),
    )
