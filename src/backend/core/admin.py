"""Admin classes and registrations for core app."""

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
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


class BulkSiretImportForm(forms.ModelForm):
    """Form for bulk importing SIRETs to create OperatorOrganizationRole entries."""

    siret_list = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 15,
                "cols": 50,
                "placeholder": _(
                    "Enter one SIRET per line:\n12345678901234\n98765432109876\n..."
                ),
            }
        ),
        label=_("SIRET List"),
        help_text=_(
            "Enter one SIRET per line. Only 14-digit SIRET codes will be processed."
        ),
    )

    class Meta:
        model = models.OperatorOrganizationRole
        fields = ["operator", "role"]
        widgets = {
            "operator": forms.Select(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active operators
        self.fields["operator"].queryset = models.Operator.objects.filter(
            is_active=True
        )
        self.fields["operator"].empty_label = _("Select an operator...")

        # Set default role
        self.fields["role"].initial = "admin"

    def clean_siret_list(self):
        """Clean and validate the SIRET list."""
        siret_list = self.cleaned_data.get("siret_list", "")
        if not siret_list.strip():
            raise forms.ValidationError(_("Please enter at least one SIRET."))

        # Split by lines and clean
        siret_lines = [line.strip() for line in siret_list.split("\n") if line.strip()]

        if not siret_lines:
            raise forms.ValidationError(_("Please enter at least one valid SIRET."))

        # Validate SIRET format (14 digits)
        valid_sirets = []
        invalid_sirets = []

        for siret in siret_lines:
            # Remove any spaces or dashes
            clean_siret = siret.replace(" ", "").replace("-", "")
            if clean_siret.isdigit() and len(clean_siret) == 14:
                valid_sirets.append(clean_siret)
            else:
                invalid_sirets.append(siret)

        if invalid_sirets:
            raise forms.ValidationError(
                _("Invalid SIRET format: {}. SIRETs must be exactly 14 digits.").format(
                    ", ".join(invalid_sirets[:5])
                    + ("..." if len(invalid_sirets) > 5 else "")
                )
            )

        return valid_sirets


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
    readonly_fields = ("id", "computed_contribution", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("name", "url", "is_active")}),
        (_("Financial Information"), {"fields": ("computed_contribution",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )
    autocomplete_fields = ["users"]
    inlines = [OperatorUsersInline]

    def computed_contribution(self, obj):
        """Display the computed financial contribution of the operator."""
        if obj.pk:
            details = obj.compute_contribution()
            return (
                f"""{details["communes"]} communes >3500 (parmi {details["all_communes"]} communes) :"""
                + f""" {details["population_in_communes"]:,.0f} habitants\n"""
                + f""" {details["communes_in_epcis"]} communes >3500 dans {details["all_epcis"]} EPCIs :"""
                + f""" {details["population_in_epcis"]:,.0f} habitants\n"""
                + f""" Total : {details["population"]:,.0f} habitants\n"""
                + f""" Base: {details["base_contribution"]:,.2f} €\n"""
                + """ Usage: N/A\n"""
                + f""" Contribution finale: {details["contribution"]:,.2f} €\n"""
            )
        return "N/A"

    computed_contribution.short_description = _("Computed Contribution")


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


class OperatorFilter(admin.SimpleListFilter):
    """Custom filter for operators."""

    title = _("Operator")
    parameter_name = "operator"

    def lookups(self, request, model_admin):
        # Get all operators that have organization roles
        operators = (
            models.Operator.objects.filter(organization_roles__isnull=False)
            .distinct()
            .order_by("name")
        )

        return [(op.id, op.name) for op in operators]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(operator_id=self.value())
        return queryset


class AboveContributionThresholdFilter(admin.SimpleListFilter):
    """Filter to show only organizations above the contribution threshold."""

    title = _("Above Contribution Threshold")
    parameter_name = "above_threshold"

    def lookups(self, request, model_admin):
        return (
            ("yes", _("Yes")),
            ("no", _("No")),
        )

    def queryset(self, request, queryset):
        threshold = settings.OPERATOR_CONTRIBUTION_POPULATION_THRESHOLD

        if self.value() == "yes":
            return queryset.filter(organization__population__gt=threshold)
        if self.value() == "no":
            return queryset.filter(organization__population__lte=threshold)
        return queryset


@admin.register(models.OperatorOrganizationRole)
class OperatorOrganizationRoleAdmin(admin.ModelAdmin):
    """Admin class for the OperatorOrganizationRole model"""

    list_display = (
        "operator",
        "organization",
        "organization_population",
        "role",
        "created_at",
    )
    list_filter = (
        "role",
        OperatorFilter,
        "organization__type",
        "created_at",
        AboveContributionThresholdFilter,
    )
    search_fields = ("operator__name", "organization__name")
    ordering = ("operator__name", "organization__name")
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["operator", "organization"]

    fieldsets = (
        (None, {"fields": ("operator", "organization", "role")}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )

    def organization_population(self, obj):
        """Display the organization's population."""
        if obj.organization and obj.organization.population:
            return f"{obj.organization.population:,}"
        return "N/A"

    organization_population.short_description = _("Population")
    organization_population.admin_order_field = "organization__population"

    def get_form(self, request, obj=None, change=False, **kwargs):
        """Return the form class for the admin view."""
        if (
            request.resolver_match.url_name
            == "core_operatororganizationrole_bulk_import"
        ):
            return BulkSiretImportForm
        return super().get_form(request, obj, change, **kwargs)

    def get_fieldsets(self, request, obj=None):
        """Define fieldsets for the bulk import form."""
        if (
            request.resolver_match.url_name
            == "core_operatororganizationrole_bulk_import"
        ):
            return (
                (None, {"fields": ("operator", "role")}),
                (_("SIRET Import"), {"fields": ("siret_list",)}),
            )
        return self.fieldsets

    def get_urls(self):
        """Add custom URLs for bulk import functionality."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "bulk-import/",
                self.admin_site.admin_view(self.bulk_import_view),
                name="core_operatororganizationrole_bulk_import",
            ),
            path(
                "bulk-import-results/",
                self.admin_site.admin_view(self.bulk_import_results_view),
                name="core_operatororganizationrole_bulk_import_results",
            ),
        ]
        return custom_urls + urls

    def bulk_import_view(self, request):
        """View for bulk importing SIRETs using native admin form rendering."""
        if request.method == "POST":
            form = BulkSiretImportForm(request.POST)
            if form.is_valid():
                operator = form.cleaned_data["operator"]
                role = form.cleaned_data["role"]
                siret_list = form.cleaned_data["siret_list"]

                # Process SIRETs
                created_count = 0
                not_found_sirets = []
                already_exists_count = 0

                with transaction.atomic():
                    for siret in siret_list:
                        try:
                            organization = models.Organization.objects.get(siret=siret)

                            # Check if the relationship already exists
                            if models.OperatorOrganizationRole.objects.filter(
                                operator=operator, organization=organization
                            ).exists():
                                already_exists_count += 1
                                continue

                            # Create the relationship
                            models.OperatorOrganizationRole.objects.create(
                                operator=operator, organization=organization, role=role
                            )
                            created_count += 1

                        except models.Organization.DoesNotExist:
                            not_found_sirets.append(siret)

                # Show success message with detailed results
                message_parts = [
                    _("Bulk import completed:"),
                    _("{created} created").format(created=created_count),
                    _("{already_exists} already existed").format(
                        already_exists=already_exists_count
                    ),
                    _("{not_found} not found").format(not_found=len(not_found_sirets)),
                ]

                if not_found_sirets:
                    message_parts.append(
                        _("SIRETs not found: {sirets}").format(
                            sirets=", ".join(not_found_sirets[:10])
                            + ("..." if len(not_found_sirets) > 10 else "")
                        )
                    )

                # Store results in session for results page
                request.session["bulk_import_results"] = {
                    "created_count": created_count,
                    "not_found_sirets": not_found_sirets,
                    "already_exists_count": already_exists_count,
                    "operator_name": operator.name,
                    "role": role,
                    "total_processed": len(siret_list),
                }

                # Show success message
                messages.success(
                    request,
                    _(
                        "Bulk import completed: {created} created, "
                        + "{already_exists} already existed, {not_found} not found."
                    ).format(
                        created=created_count,
                        already_exists=already_exists_count,
                        not_found=len(not_found_sirets),
                    ),
                )

                return HttpResponseRedirect(
                    reverse("admin:core_operatororganizationrole_bulk_import_results")
                )
        else:
            form = BulkSiretImportForm()

        # Use Django's native admin add_view method with custom form
        return self.add_view(request, extra_context={"title": _("Bulk Import SIRETs")})

    def bulk_import_results_view(self, request):
        """View for displaying bulk import results."""
        results = request.session.get("bulk_import_results")
        if not results:
            messages.error(request, _("No bulk import results found."))
            return HttpResponseRedirect(
                reverse("admin:core_operatororganizationrole_changelist")
            )

        # Clear the session data after displaying
        del request.session["bulk_import_results"]

        context = {
            "results": results,
            "title": _("Bulk Import Results"),
            "opts": self.model._meta,  # pylint: disable=protected-access # noqa: SLF001
            "has_view_permission": self.has_view_permission(request),
        }

        return render(
            request,
            "admin/core/operatororganizationrole/bulk_import_results.html",
            context,
        )

    def changelist_view(self, request, extra_context=None):
        """Add bulk import link to changelist view."""
        extra_context = extra_context or {}
        extra_context["bulk_import_url"] = reverse(
            "admin:core_operatororganizationrole_bulk_import"
        )
        return super().changelist_view(request, extra_context)


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
