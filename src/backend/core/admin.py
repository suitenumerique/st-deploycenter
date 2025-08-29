"""Admin classes and registrations for core app."""

from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _

from . import models


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
        "full_name",
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
        (_("Users"), {"fields": ("users",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )
    autocomplete_fields = ["users"]


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
                )
            },
        ),
        (
            _("Population Data"),
            {"fields": ("population", "epci_libelle", "epci_siren", "epci_population")},
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


@admin.register(models.Service)
class ServiceAdmin(admin.ModelAdmin):
    """Admin class for the Service model"""

    list_display = ("type", "url", "description", "config", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("type", "description")
    ordering = ("type", "url")
    readonly_fields = ("id", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("type", "url", "description", "is_active")}),
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


@admin.register(models.ServiceSubscription)
class ServiceSubscriptionAdmin(admin.ModelAdmin):
    """Admin class for the ServiceSubscription model"""

    list_display = ("organization", "service", "created_at")
    list_filter = ("organization__operator_roles__operator", "created_at")
    search_fields = ("organization__name", "service__type")
    ordering = ("organization__name", "service__type")
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

    list_display = ("name", "value", "organization", "timestamp", "created_at")
    list_filter = ("timestamp", "organization__operator_roles__operator", "created_at")
    search_fields = ("name", "organization__name", "service__type")
    ordering = ("-timestamp", "name")
    readonly_fields = ("id", "timestamp", "created_at", "updated_at")

    autocomplete_fields = ["service", "organization"]

    fieldsets = (
        (None, {"fields": ("name", "value")}),
        (_("Relationships"), {"fields": ("service", "organization")}),
        (_("Metadata"), {"fields": ("timestamp", "created_at", "updated_at")}),
    )
