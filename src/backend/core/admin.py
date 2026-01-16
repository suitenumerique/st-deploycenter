# pylint: disable=line-too-long,too-many-lines
"""Admin classes and registrations for core app."""

import secrets

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
            "instance_name",
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


class PasswordlessUserCreationForm(forms.ModelForm):
    """Custom form for creating passwordless OIDC users with only identity email."""

    email = forms.EmailField(
        label=_("Identity email address"),
        required=True,
        help_text=_(
            "Required. The identity email address that will be used to merge "
            "the account when the user connects with OIDC."
        ),
    )

    class Meta:
        model = models.User
        fields = ("email",)

    def clean_email(self):
        """Validate that the email is unique."""
        email = self.cleaned_data.get("email")
        if email:
            # Check if email is already used by another user
            existing_user = models.User.objects.filter(email=email).first()
            if existing_user and (
                not self.instance.pk or existing_user.pk != self.instance.pk
            ):
                raise forms.ValidationError(
                    _("A user with this identity email address already exists.")
                )
        return email

    def save(self, commit=True):
        """Save the user, setting an unusable password for passwordless users."""
        user = super().save(commit=False)
        # Set an unusable password for passwordless users
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class BulkSiretImportForm(forms.ModelForm):
    """Form for bulk importing SIRETs or SIRENs to create OperatorOrganizationRole entries."""

    siret_list = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 15,
                "cols": 50,
                "placeholder": _(
                    "Enter one SIRET (14 digits), SIREN (9 digits), or INSEE code (5 digits) per line:\n12345678901234\n987654321\n12345\n..."
                ),
            }
        ),
        label=_("SIRET/SIREN/INSEE List"),
        help_text=_(
            "Enter one SIRET (14 digits), SIREN (9 digits), or INSEE code (5 digits for communes) per line. All formats are accepted."
        ),
    )

    expand_epci_to_communes = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Expand EPCIs to commune members"),
        help_text=_(
            "When checked, EPCI SIRETs/SIRENs will be expanded to create relationships "
            "for all commune members of the EPCI instead of the EPCI itself."
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
        """Clean and validate the SIRET/SIREN/INSEE list."""
        siret_list = self.cleaned_data.get("siret_list", "")
        if not siret_list.strip():
            raise forms.ValidationError(
                _("Please enter at least one SIRET, SIREN, or INSEE code.")
            )

        # Split by lines and clean
        siret_lines = [line.strip() for line in siret_list.split("\n") if line.strip()]

        if not siret_lines:
            raise forms.ValidationError(
                _("Please enter at least one valid SIRET, SIREN, or INSEE code.")
            )

        # Validate SIRET (14 digits), SIREN (9 digits), or INSEE code (5 digits) format
        valid_codes = []
        invalid_codes = []

        for code in siret_lines:
            # Remove any spaces or dashes
            clean_code = code.replace(" ", "").replace("-", "")
            if clean_code.isdigit() and len(clean_code) in (5, 9, 14):
                valid_codes.append(clean_code)
            else:
                invalid_codes.append(code)

        if invalid_codes:
            raise forms.ValidationError(
                _(
                    "Invalid format: {}. SIRETs must be exactly 14 digits, "
                    "SIRENs must be exactly 9 digits, "
                    "INSEE codes must be exactly 5 digits."
                ).format(
                    ", ".join(invalid_codes[:5])
                    + ("..." if len(invalid_codes) > 5 else "")
                )
            )

        return valid_codes


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
                "fields": ("admin_email", "password1", "password2"),
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

    def get_urls(self):
        """Add custom URLs for passwordless user creation."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "add-passwordless/",
                self.admin_site.admin_view(self.add_passwordless_view),
                name="core_user_add_passwordless",
            ),
        ]
        return custom_urls + urls

    def add_passwordless_view(self, request):
        """View for creating passwordless OIDC users."""
        if request.method == "POST":
            form = PasswordlessUserCreationForm(request.POST)
            if form.is_valid():
                user = form.save()
                messages.success(
                    request,
                    _('Passwordless user "%(name)s" was created successfully.')
                    % {"name": user.email or user.id},
                )
                return HttpResponseRedirect(
                    reverse("admin:core_user_change", args=[user.pk])
                )
        else:
            form = PasswordlessUserCreationForm()

        # Render the form using Django admin template
        context = {
            **self.admin_site.each_context(request),
            "title": _("Add passwordless OIDC user"),
            "form": form,
            "opts": self.model._meta,  # pylint: disable=protected-access # noqa: SLF001
            "has_view_permission": self.has_view_permission(request),
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": self.has_change_permission(request, None),
            "has_delete_permission": self.has_delete_permission(request, None),
            "is_passwordless": True,
        }
        return render(
            request,
            "admin/core/user/add_passwordless.html",
            context,
        )

    def changelist_view(self, request, extra_context=None):
        """Add passwordless user creation link to changelist view."""
        extra_context = extra_context or {}
        extra_context["add_passwordless_url"] = reverse(
            "admin:core_user_add_passwordless"
        )
        return super().changelist_view(request, extra_context)


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
        (_("Configuration"), {"fields": ("config",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )
    autocomplete_fields = ["users"]
    inlines = [OperatorUsersInline]

    def computed_contribution(self, obj):
        """Display the computed financial contribution of the operator."""
        if obj.pk:
            details = obj.compute_contribution()
            return (
                f"""{details["all_communes"]} communes adhérentes en direct\n"""
                + f"""{details["all_epcis"]} EPCIs adhérents en direct\n"""
                + f"""{details["all_communes_in_epcis"]} communes membres de ces {details["all_epcis"]} EPCIs\n\n"""
                + f"""{details["communes_in_scope"]} communes uniques au total (adhérentes en direct ou via EPCI)\n"""
                + f"""{details["communes_in_scope_above_threshold"]} de ces {details["communes_in_scope"]} communes avec > 3500 habitants\n"""
                + f"""{details["population"]:,.0f} habitants dans ces {details["communes_in_scope_above_threshold"]} communes\n\n"""
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
    change_form_template = "admin/core/service/change_form.html"
    list_display = ("name", "instance_name", "type", "url", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "type", "description")
    ordering = ("name", "type", "url")
    readonly_fields = ("id", "created_at", "updated_at", "entitlements_api_key_display")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "instance_name",
                    "type",
                    "url",
                    "description",
                    "maturity",
                    "launch_date",
                    "is_active",
                    "required_services",
                )
            },
        ),
        (_("Logo"), {"fields": ("logo_svg_file",)}),
        (_("Configuration"), {"fields": ("config",)}),
        (
            _("Metadata"),
            {"fields": ("created_at", "updated_at", "entitlements_api_key_display")},
        ),
    )

    def entitlements_api_key_display(self, obj):
        """Display the API key from config."""
        if obj.config and "entitlements_api_key" in obj.config:
            return obj.config["entitlements_api_key"]
        return _("No API key set")

    entitlements_api_key_display.short_description = _("API key")

    def response_change(self, request, obj):
        """Handle the response after a change has been posted."""
        # Check if the "Generate API Key" button was clicked
        if "_generate_entitlements_api_key" in request.POST:
            # Generate a secure 64-character random string
            # Using token_hex(32) generates exactly 64 hex characters (32 bytes * 2)
            api_key = secrets.token_hex(32)

            # Ensure config dict exists
            if obj.config is None:
                obj.config = {}

            # Save the API key to config (overwrites any existing key)
            obj.config["entitlements_api_key"] = api_key
            obj.save(update_fields=["config"])

            messages.success(
                request,
                _("API key generated successfully: {}").format(api_key),
            )

            # Redirect to the same page to show the updated API key
            return HttpResponseRedirect(
                reverse("admin:core_service_change", args=[obj.pk])
            )

        # For normal form submissions, call the parent method
        return super().response_change(request, obj)


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
                (
                    _("SIRET Import"),
                    {"fields": ("siret_list", "expand_epci_to_communes")},
                ),
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

    def _create_relationship(self, operator, organization, role):
        """Create an OperatorOrganizationRole relationship if it doesn't already exist.

        Returns:
            tuple: (created: bool, already_exists: bool)
        """
        if models.OperatorOrganizationRole.objects.filter(
            operator=operator, organization=organization
        ).exists():
            return False, True

        models.OperatorOrganizationRole.objects.create(
            operator=operator, organization=organization, role=role
        )
        return True, False

    def _expand_epci_to_communes(self, epci):
        """Expand an EPCI to its commune members.

        Args:
            epci: The EPCI organization
            operator: Operator (unused, kept for consistency)
            role: Role (unused, kept for consistency)

        Returns:
            QuerySet: QuerySet of communes belonging to the EPCI
        """
        if not epci.siren:
            return models.Organization.objects.none()

        return models.Organization.objects.filter(epci_siren=epci.siren, type="commune")

    def _process_insee_code(self, code, operator, role):
        """Process a 5-digit INSEE code.

        Returns:
            tuple: (created_count: int, already_exists_count: int, not_found: bool)
        """
        organizations = models.Organization.objects.filter(
            code_insee=code, type="commune"
        )
        if not organizations.exists():
            return 0, 0, True

        created = 0
        already_exists = 0
        for organization in organizations:
            was_created, was_existing = self._create_relationship(
                operator, organization, role
            )
            if was_created:
                created += 1
            elif was_existing:
                already_exists += 1

        return created, already_exists, False

    def _process_siren_code(self, code, operator, role, expand_epci):
        """Process a 9-digit SIREN code.

        Returns:
            tuple: (created_count: int, already_exists_count: int, not_found: bool)
        """
        organizations = models.Organization.objects.filter(siren=code)
        if not organizations.exists():
            return 0, 0, True

        created = 0
        already_exists = 0

        # Separate EPCIs from other organizations
        epci_organizations = [org for org in organizations if org.type == "epci"]
        other_organizations = [org for org in organizations if org.type != "epci"]

        # Expand EPCIs to communes if expansion is enabled
        if expand_epci and epci_organizations:
            for epci in epci_organizations:
                communes = self._expand_epci_to_communes(epci)
                for commune in communes:
                    was_created, was_existing = self._create_relationship(
                        operator, commune, role
                    )
                    if was_created:
                        created += 1
                    elif was_existing:
                        already_exists += 1
        elif not expand_epci and epci_organizations:
            # If expansion is disabled, create relationships for EPCIs themselves
            for epci in epci_organizations:
                was_created, was_existing = self._create_relationship(
                    operator, epci, role
                )
                if was_created:
                    created += 1
                elif was_existing:
                    already_exists += 1

        # Process non-EPCI organizations
        for organization in other_organizations:
            was_created, was_existing = self._create_relationship(
                operator, organization, role
            )
            if was_created:
                created += 1
            elif was_existing:
                already_exists += 1

        return created, already_exists, False

    def _process_siret_code(self, code, operator, role, expand_epci):
        """Process a 14-digit SIRET code.

        Returns:
            tuple: (created_count: int, already_exists_count: int, not_found: bool)
        """
        try:
            organization = models.Organization.objects.get(siret=code)
        except models.Organization.DoesNotExist:
            return 0, 0, True

        # Check if it's an EPCI and expansion is enabled
        if expand_epci and organization.type == "epci":
            communes = self._expand_epci_to_communes(organization)
            if not communes.exists():
                return 0, 0, True

            created = 0
            already_exists = 0
            for commune in communes:
                was_created, was_existing = self._create_relationship(
                    operator, commune, role
                )
                if was_created:
                    created += 1
                elif was_existing:
                    already_exists += 1
            return created, already_exists, False

        # Not an EPCI or expansion disabled - create relationship for the organization
        was_created, was_existing = self._create_relationship(
            operator, organization, role
        )
        if was_created:
            return 1, 0, False
        if was_existing:
            return 0, 1, False
        return 0, 0, False

    def _process_bulk_import(self, siret_list, operator, role, expand_epci):
        """Process the bulk import of codes.

        Returns:
            dict: Results with created_count, already_exists_count, not_found_codes
        """
        created_count = 0
        not_found_codes = []
        already_exists_count = 0

        with transaction.atomic():
            for code in siret_list:
                code_length = len(code)

                if code_length == 5:
                    created, already_exists, not_found = self._process_insee_code(
                        code, operator, role
                    )
                elif code_length == 9:
                    created, already_exists, not_found = self._process_siren_code(
                        code, operator, role, expand_epci
                    )
                else:  # code_length == 14
                    created, already_exists, not_found = self._process_siret_code(
                        code, operator, role, expand_epci
                    )

                created_count += created
                already_exists_count += already_exists
                if not_found:
                    not_found_codes.append(code)

        return {
            "created_count": created_count,
            "already_exists_count": already_exists_count,
            "not_found_codes": not_found_codes,
        }

    def _handle_import_results(self, request, results, operator, role, siret_list):
        """Handle the results of a bulk import operation."""
        # Store results in session for results page
        request.session["bulk_import_results"] = {
            **results,
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
                created=results["created_count"],
                already_exists=results["already_exists_count"],
                not_found=len(results["not_found_codes"]),
            ),
        )

        return HttpResponseRedirect(
            reverse("admin:core_operatororganizationrole_bulk_import_results")
        )

    def bulk_import_view(self, request):
        """View for bulk importing SIRETs using native admin form rendering."""
        if request.method == "POST":
            form = BulkSiretImportForm(request.POST)
            if form.is_valid():
                operator = form.cleaned_data["operator"]
                role = form.cleaned_data["role"]
                siret_list = form.cleaned_data["siret_list"]
                expand_epci = form.cleaned_data.get("expand_epci_to_communes", False)

                results = self._process_bulk_import(
                    siret_list, operator, role, expand_epci
                )
                return self._handle_import_results(
                    request, results, operator, role, siret_list
                )
        else:
            form = BulkSiretImportForm()

        # Use Django's native admin add_view method with custom form
        return self.add_view(
            request, extra_context={"title": _("Bulk Import SIRETs/SIRENs/INSEE")}
        )

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

    list_display = (
        "operator",
        "service",
        "display_priority",
        "externally_managed",
        "created_at",
    )
    list_filter = ("operator", "service__is_active", "externally_managed", "created_at")
    search_fields = ("operator__name", "service__name", "service__type")
    ordering = ("operator__name", "display_priority", "service__name")
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["operator", "service"]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "operator",
                    "service",
                    "display_priority",
                    "externally_managed",
                )
            },
        ),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(models.ServiceSubscription)
class ServiceSubscriptionAdmin(admin.ModelAdmin):
    """Admin class for the ServiceSubscription model"""

    list_display = ("organization", "operator", "service", "created_at")
    list_filter = ("organization__operator_roles__operator", "created_at")
    search_fields = (
        "organization__name",
        "service__name",
        "service__type",
        "operator__name",
    )
    ordering = ("organization__name", "service__name")
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["organization", "operator", "service"]

    fieldsets = (
        (None, {"fields": ("organization", "operator", "service", "is_active")}),
        (_("Subscription Data"), {"fields": ("metadata",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(models.Metric)
class MetricAdmin(admin.ModelAdmin):
    """Admin class for the Metric model"""

    list_display = ("key", "value", "service", "organization", "timestamp")
    list_filter = ("timestamp", "organization__operator_roles__operator", "service")
    search_fields = ("key", "organization__name", "service__name", "service__type")
    ordering = ("-timestamp", "key")
    readonly_fields = ("id", "timestamp")

    autocomplete_fields = ["service", "organization"]

    fieldsets = (
        (None, {"fields": ("key", "value")}),
        (_("Relationships"), {"fields": ("service", "organization")}),
        (_("Metadata"), {"fields": ("timestamp",)}),
    )


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    """Admin class for the Account model"""

    list_display = ("id", "external_id", "type", "email", "organization")
    list_filter = ("type", "organization__operator_roles__operator")
    search_fields = ("external_id", "email", "organization__name")
    ordering = ("organization__name", "type", "external_id")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ["organization"]


@admin.register(models.Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    """Admin class for the Entitlement model"""

    list_display = ("service_subscription", "type", "account_type", "account")
    list_filter = ("type", "account_type", "created_at")
    search_fields = (
        "service_subscription__organization__name",
        "type",
        "account_type",
        "account_id",
    )
    ordering = (
        "service_subscription__organization__name",
        "type",
        "account_type",
        "account_id",
    )
    readonly_fields = ("id", "created_at", "updated_at")

    autocomplete_fields = ["service_subscription"]
