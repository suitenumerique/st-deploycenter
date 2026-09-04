"""Client serializers for the deploycenter core app."""
# pylint: disable=too-many-lines

from collections import defaultdict
from collections.abc import Mapping

from django.db.models import Q

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models
from core.entitlements.resolvers import TYPE_TO_ADMIN_RESOLVER
from core.entitlements.resolvers.extended_admin_entitlement_resolver import (
    ExtendedAdminEntitlementResolver,
)
from core.services import domainnames, get_service_handler, locks
from core.services import domains as domains_service
from core.services import proconnect as proconnect_service


class IntegerChoicesField(serializers.ChoiceField):
    """
    Custom field to handle IntegerChoices that accepts string labels for input
    and returns string labels for output.

    Example usage:
        role = IntegerChoicesField(choices=MailboxRoleChoices)

    This field will:
    - Accept strings like "viewer", "editor", "admin" for input
    - Store them as integers (1, 2, 4) in the database
    - Return strings like "viewer", "editor", "admin" for output
    - Provide helpful error messages for invalid choices
    - Support backward compatibility with integer input
    """

    def __init__(self, choices_class, **kwargs):
        super().__init__(choices=choices_class.choices, **kwargs)
        self._override_spectacular_annotation(choices_class)

    def _override_spectacular_annotation(self, choices_class):
        """
        Override the OpenAPI annotation for the field.
        This method has the same effect than `extend_schema_field` decorator.
        We do that only to be able to use class attributes as choices that is not possible with the decorator.
        https://drf-spectacular.readthedocs.io/en/latest/drf_spectacular.html#drf_spectacular.utils.extend_schema_field
        """
        self._spectacular_annotation = {
            "field": {
                "type": "string",
                "enum": [label for _value, label in choices_class.choices],
            },
            "field_component_name": choices_class.__name__,
        }

    @extend_schema_field(
        {
            "type": "string",
            "enum": None,  # This will be set dynamically
            "description": "Choice field that accepts string labels and returns string labels",
        }
    )
    def to_representation(self, value):
        """Convert integer value to string label for output."""
        if value is None:
            return None
        enum_instance = self.choices[value]
        return enum_instance

    def to_internal_value(self, data):
        """Convert string label to integer value for storage."""
        if data is None:
            return None

        # If it's already an integer (for backward compatibility), validate and return it
        if isinstance(data, int):
            try:
                # Validate it's a valid choice
                self.choices[data]  # pylint: disable=pointless-statement
                return data
            except KeyError:
                self.fail("invalid_choice", input=data)

        # Convert string label to integer value
        if isinstance(data, str):
            for choice_value, choice_label in self.choices.items():
                if choice_label == data:
                    return choice_value
            self.fail("invalid_choice", input=data)

        self.fail("invalid_choice", input=data)

        return None

    default_error_messages = {
        "invalid_choice": "Invalid choice: {input}. Valid choices are: {choices}."
    }

    def fail(self, key, **kwargs):
        """Override to provide better error messages."""
        if key == "invalid_choice":
            valid_choices = [label for value, label in self.choices.items()]
            kwargs["choices"] = ", ".join(valid_choices)
        super().fail(key, **kwargs)


class UserSerializer(serializers.ModelSerializer):
    """Serialize users."""

    class Meta:
        model = models.User
        fields = ["id", "email", "full_name", "language", "is_superuser"]
        read_only_fields = ["id", "email", "full_name", "is_superuser"]


# Subscription check serializers
class SubscriptionCheckRequestSerializer(serializers.Serializer):
    """Serializer for subscription check requests."""

    siret = serializers.CharField(required=False, help_text="SIRET code (14 digits)")
    insee = serializers.CharField(required=False, help_text="INSEE code (5 digits)")

    def create(self, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError("This serializer is for validation only")

    def update(self, instance, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError("This serializer is for validation only")


class SubscriptionCheckResponseSerializer(serializers.Serializer):
    """Serializer for subscription check responses."""

    has_subscription = serializers.BooleanField(
        help_text="Whether the organization has an active subscription"
    )
    organization_id = serializers.UUIDField(
        help_text="Organization ID if subscription exists", allow_null=True
    )
    organization_name = serializers.CharField(
        help_text="Organization name if subscription exists", allow_null=True
    )
    subscription_id = serializers.UUIDField(
        help_text="Subscription ID if subscription exists", allow_null=True
    )
    service_id = serializers.UUIDField(help_text="Service ID", allow_null=True)
    service_name = serializers.CharField(help_text="Service type", allow_null=True)

    error_message = serializers.CharField(
        help_text="Error message if validation failed", allow_null=True
    )

    def create(self, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError("This serializer is for validation only")

    def update(self, instance, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError("This serializer is for validation only")


class OrganizationIdentifierSerializer(serializers.Serializer):
    """
    Serializer for organization identifier validation and lookup.

    Accepts exactly one of: siret, siren, or insee.
    Validates format and returns the corresponding organization.
    """

    siret = serializers.CharField(
        required=False, allow_blank=True, help_text="SIRET code (14 digits)"
    )
    siren = serializers.CharField(
        required=False, allow_blank=True, help_text="SIREN code (9 digits)"
    )
    insee = serializers.CharField(
        required=False, allow_blank=True, help_text="INSEE code (5 digits)"
    )

    def validate(self, attrs):
        """Validate that at most one identifier is provided and has correct format."""
        # Get non-empty identifiers
        identifiers = {
            key: value.strip()
            for key, value in attrs.items()
            if value and value.strip()
        }

        # If no identifiers provided, that's OK for organization-less mode
        if len(identifiers) == 0:
            return attrs

        if len(identifiers) > 1:
            raise serializers.ValidationError(
                "Cannot provide multiple identifiers. Use exactly one of: siret, siren, or insee"
            )

        # Validate format of the provided identifier
        identifier_type, identifier_value = next(iter(identifiers.items()))

        if identifier_type == "autodetect_id":
            if len(identifier_value) == 14 and identifier_value.isdigit():
                identifier_type = "siret"
            elif len(identifier_value) == 9 and identifier_value.isdigit():
                identifier_type = "siren"
            elif len(identifier_value) == 5 and identifier_value.isdigit():
                identifier_type = "insee"
            else:
                raise serializers.ValidationError(
                    {
                        "autodetect_id": "Invalid ID format. Must be SIRET, SIREN, or INSEE."
                    }
                )

        if identifier_type == "siret":
            if not (len(identifier_value) == 14 and identifier_value.isdigit()):
                raise serializers.ValidationError(
                    {"siret": "Invalid SIRET format. Must be 14 digits."}
                )
        elif identifier_type == "siren":
            if not (len(identifier_value) == 9 and identifier_value.isdigit()):
                raise serializers.ValidationError(
                    {"siren": "Invalid SIREN format. Must be 9 digits."}
                )
        elif identifier_type == "insee":
            if not (len(identifier_value) == 5 and identifier_value.isdigit()):
                raise serializers.ValidationError(
                    {"insee": "Invalid INSEE format. Must be 5 digits."}
                )

        # Store the validated identifier info
        attrs["_identifier_type"] = identifier_type
        attrs["_identifier_value"] = identifier_value

        return attrs

    def get_organization(self):
        """
        Retrieve the organization based on the validated identifier.

        Returns:
            Organization or None: The organization object, or None if no identifier provided
        Raises:
            serializers.ValidationError: If organization is not found
        """
        validated_data = self.validated_data

        # Check if no identifier was provided (organization-less mode)
        if "_identifier_type" not in validated_data:
            return None

        identifier_type = validated_data["_identifier_type"]
        identifier_value = validated_data["_identifier_value"]

        # Look up organization by identifier
        if identifier_type == "siret":
            organization = models.Organization.objects.filter(
                siret=identifier_value
            ).first()
        elif identifier_type == "siren":
            organization = models.Organization.objects.filter(
                siren=identifier_value
            ).first()
        elif identifier_type == "insee":
            organization = models.Organization.objects.filter(
                code_insee=identifier_value
            ).first()
        else:
            raise serializers.ValidationError("Invalid identifier type")

        if not organization:
            raise serializers.ValidationError(
                f"Organization not found with {identifier_type}: {identifier_value}"
            )

        return organization

    def create(self, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError("This serializer is for validation only")

    def update(self, instance, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError("This serializer is for validation only")


class OperatorSerializer(serializers.ModelSerializer):
    """Serialize operators."""

    user_role = serializers.SerializerMethodField(read_only=True)
    config = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Operator
        fields = ["id", "name", "siret", "url", "is_active", "user_role", "config"]
        read_only_fields = fields

    def get_user_role(self, obj):
        """Get the user role for the operator."""
        roles = obj.user_roles.all()
        if roles.count() > 0:
            return roles[0].role
        return None

    def get_config(self, obj):
        """
        Get the configuration for the operator.
        We don't expose all the configuration, because it may contain sensitive data.
        """
        config = obj.config or {}
        whitelist_keys = ["idps", "support_email"]
        return {key: config[key] for key in whitelist_keys if key in config}


class ServiceSerializer(serializers.ModelSerializer):
    """Serialize services."""

    logo = serializers.CharField(source="get_logo_url", read_only=True)
    config = serializers.SerializerMethodField(read_only=True)
    entitlement_defaults = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Service
        fields = [
            "id",
            "name",
            "instance_name",
            "type",
            "url",
            "description",
            "maturity",
            "launch_date",
            "is_active",
            "hidden",
            "created_at",
            "logo",
            "config",
            "entitlement_defaults",
        ]
        read_only_fields = fields

    def get_config(self, obj):
        """Get the configuration for the service."""
        config = obj.config or {}
        whitelist_keys = [
            "help_center_url",
            "population_limits",
            "auto_admin_population_threshold",
            "idp_id",
        ]
        return {key: config[key] for key in whitelist_keys if key in config}

    def get_entitlement_defaults(self, obj):
        """Get the default entitlement configurations for this service type."""
        handler = get_service_handler(obj)
        if handler:
            return handler.get_default_entitlements()
        return []


class ServiceLightSerializer(serializers.ModelSerializer):
    """Serialize services."""

    class Meta:
        model = models.Service
        fields = ["id", "name", "instance_name", "type"]
        read_only_fields = fields


class EntitlementSerializer(serializers.ModelSerializer):
    """Serialize entitlements."""

    class Meta:
        model = models.Entitlement
        fields = ["id", "type", "config", "account_type", "account"]
        read_only_fields = ["id", "type"]


class EntitlementConfigInputSerializer(serializers.Serializer):
    """Serializer for entitlement config input when creating/updating subscriptions.

    This is a read-only serializer used only for validation of entitlement config input.
    """

    type = serializers.CharField()
    account_type = serializers.CharField()
    config = serializers.DictField()

    def create(self, validated_data):
        """Not used - this serializer is only for validation."""
        raise NotImplementedError("This serializer is read-only")

    def update(self, instance, validated_data):
        """Not used - this serializer is only for validation."""
        raise NotImplementedError("This serializer is read-only")


class ServiceSubscriptionSerializer(serializers.ModelSerializer):
    """Serialize service subscriptions."""

    entitlements = EntitlementSerializer(many=True, read_only=True)
    # Write-only field for setting entitlement configs during create/update
    entitlements_input = EntitlementConfigInputSerializer(
        many=True, write_only=True, required=False, source="entitlements"
    )

    class Meta:
        model = models.ServiceSubscription
        fields = [
            "metadata",
            "created_at",
            "updated_at",
            "is_active",
            "entitlements",
            "entitlements_input",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store entitlement configs to apply after save (instance-level, not class-level)
        self._pending_entitlement_configs = None

    def to_internal_value(self, data):
        """Extract entitlements input before validation."""
        if not isinstance(data, Mapping):
            # `{**data}` would TypeError on a list or scalar body. DRF's own check
            # for this lives in super().to_internal_value, which runs after us.
            raise serializers.ValidationError(
                {"non_field_errors": ["Invalid data. Expected a dictionary."]}
            )
        # Work on a shallow copy to avoid mutating the original input
        data = {**data}
        # BOTH names must come out before super(): "entitlements" is what clients
        # send, "entitlements_input" is the declared write field (its source is
        # "entitlements"). Either one left in place lands in validated_data as a
        # writable nested field, which ModelSerializer.update() asserts against —
        # a 500 on caller-controlled input.
        entitlements_data = data.pop("entitlements", None)
        aliased = data.pop("entitlements_input", None)
        if entitlements_data is None:
            entitlements_data = aliased
        result = super().to_internal_value(data)
        if entitlements_data is not None:
            # Validate entitlements input
            entitlements_serializer = EntitlementConfigInputSerializer(
                data=entitlements_data, many=True
            )
            entitlements_serializer.is_valid(raise_exception=True)
            self._pending_entitlement_configs = entitlements_serializer.validated_data
        return result

    def update(self, instance, validated_data):
        """Update subscription and apply entitlement configs."""
        instance = super().update(instance, validated_data)
        self.apply_entitlement_configs(instance)
        return instance

    def _validate_entitlement_types(self, service):
        """Validate pending entitlement types are appropriate for the service.

        Runs at ``validate()`` time (during ``is_valid()``), i.e. *before* the
        subscription is saved — so an invalid type raises a 400 before any
        ProConnect push happens, instead of rolling one back afterwards.
        """
        if not self._pending_entitlement_configs or service is None:
            return

        handler = get_service_handler(service)
        valid_types = set()
        if handler:
            valid_types = {d["type"] for d in handler.get_default_entitlements()}
        valid_enum_types = [t.value for t in models.Entitlement.EntitlementType]

        for config_data in self._pending_entitlement_configs:
            entitlement_type = config_data["type"]

            # Only validate against the handler when it defines valid types.
            if valid_types and entitlement_type not in valid_types:
                raise serializers.ValidationError(
                    {
                        "entitlements": f"Entitlement type '{entitlement_type}' is not valid "
                        f"for service type '{service.type}'. "
                        f"Valid types: {', '.join(str(t) for t in valid_types)}"
                    }
                )

            if entitlement_type not in valid_enum_types:
                raise serializers.ValidationError(
                    {
                        "entitlements": f"Unknown entitlement type '{entitlement_type}'. "
                        f"Valid types: {', '.join(valid_enum_types)}"
                    }
                )

    def apply_entitlement_configs(self, subscription):
        """Persist pending entitlement configs on the subscription.

        Only updates default entitlements (where account=None); account-specific
        entitlements are never modified. Types are validated up-front in
        :meth:`_validate_entitlement_types` (at ``is_valid()`` time).
        """
        if not self._pending_entitlement_configs:
            return

        for config_data in self._pending_entitlement_configs:
            # Only update default entitlements (account=None), never account-specific ones
            # Use update_or_create for atomic operation
            subscription.entitlements.update_or_create(
                type=config_data["type"],
                account_type=config_data["account_type"],
                account=None,
                defaults={"config": config_data["config"]},
            )

    VALID_AUTO_ADMIN_VALUES = ("all", "manual")

    def _validate_proconnect_subscription(self, attrs):
        """
        Validate ProConnect subscription data.
        Handles both update (instance exists) and create (no instance) cases.
        IDP is now stored in Service.config.idp_id (immutable per service).
        """
        service_type = self._get_service_type()
        if service_type != "proconnect":
            return

        instance = self.instance
        organization = self._get_organization()

        # `or {}`: a row whose metadata was nulled outside the API (admin, import)
        # must stay editable rather than 500 here. Same guard as the domains one.
        current_metadata = (instance.metadata if instance else {}) or {}
        is_active = attrs.get("is_active", instance.is_active if instance else True)

        mail_domain = organization.mail_domain if organization else None
        existing_domains = current_metadata.get("domains")
        submitted_domains = attrs.get("metadata", {}).get("domains")

        # Shape first, whatever the caller's role. A non-list (or a list holding a
        # number/dict) used to fall through to the "not submitted" branch, so the
        # caller got a 200 carrying domains it never sent — the silent-drop the
        # rest of this module refuses on principle.
        if submitted_domains is not None and (
            not isinstance(submitted_domains, list)
            or not all(isinstance(d, str) for d in submitted_domains)
        ):
            raise serializers.ValidationError(
                {"metadata": "domains must be a list of domain strings."}
            )

        if submitted_domains is not None:
            # Same rule as every other domain write: refuse what normalization
            # would otherwise drop, or the UI shows a routed domain we never push.
            # Only what the caller sends is refused — a malformed domain already
            # stored (older write, bad import) must not block deactivating or
            # otherwise editing the subscription; it is normalized away below.
            invalid = domainnames.invalid_domains(submitted_domains)
            if invalid:
                raise serializers.ValidationError(
                    {"metadata": f"Not valid domain name(s): {', '.join(invalid)}."}
                )
            if not self._is_superuser():
                # Any operator member may change the routing, but only within what
                # the organization may already route — the exact set the modal
                # offers (`proconnect_routable`). Refusing is the point: silently
                # forcing the list back, as this used to, answered 200 with domains
                # the caller never sent. Superusers keep the override.
                # Fails closed: no organization resolved -> nothing is routable.
                allowed = (
                    set(proconnect_service.routable_domains(organization))
                    if organization
                    else set()
                )
                refused = sorted(set(submitted_domains) - allowed)
                if refused:
                    raise serializers.ValidationError(
                        {
                            "metadata": (
                                f"Domain(s) not routable for this organization: "
                                f"{', '.join(refused)}."
                            )
                        }
                    )
            resolved_domains = submitted_domains
        else:
            resolved_domains = existing_domains or (
                [mail_domain] if mail_domain else []
            )

        resolved_domains = domainnames.normalize_domains(resolved_domains)

        # When activating a subscription, we must have a valid domain.
        if is_active and not resolved_domains:
            raise serializers.ValidationError(
                {"metadata": "Mail domain is required for ProConnect subscription."}
            )

        # Domain uniqueness: no two active ProConnect subscriptions may share
        # a domain (across all organizations and operators).
        # Uses JSON containment queries to find conflicts at the DB level
        # instead of iterating all subscriptions in Python.
        # select_for_update prevents TOCTOU races (locks held until the
        # view-level transaction commits).
        if resolved_domains and is_active:
            # Lock each domain first: select_for_update below can only lock rows
            # that already exist, so without this two transactions activating the
            # same domain on different subscriptions both see "no conflict".
            locks.lock_domains(resolved_domains)

            current_sub_id = instance.pk if instance else None
            overlap_q = Q()
            for domain in resolved_domains:
                overlap_q |= Q(metadata__domains__contains=[domain])

            conflicting_subs = (
                models.ServiceSubscription.objects.filter(
                    overlap_q,
                    service__type="proconnect",
                    is_active=True,
                )
                .select_for_update()
                .exclude(pk=current_sub_id)
                .values_list("metadata", flat=True)
            )

            overlap = set()
            for meta in conflicting_subs:
                existing = {
                    d.strip().lower()
                    for d in (meta or {}).get("domains", [])
                    if isinstance(d, str)
                }
                overlap |= existing & set(resolved_domains)

            if overlap:
                raise serializers.ValidationError(
                    {
                        "metadata": (
                            f"Domain(s) {', '.join(sorted(overlap))} "
                            f"already used by another active "
                            f"ProConnect subscription."
                        )
                    }
                )

        # Build the metadata dict explicitly
        attrs["metadata"] = {
            "domains": resolved_domains,
        }

    @staticmethod
    def _clean_domain_list(value, field):
        """Validate and normalize one domain list of the ``domains`` metadata."""
        if not isinstance(value, list) or not all(isinstance(d, str) for d in value):
            raise serializers.ValidationError(
                {field: "Must be a list of domain strings."}
            )
        if len(value) > domainnames.MAX_DOMAINS:
            raise serializers.ValidationError(
                {field: f"Too many domains (max {domainnames.MAX_DOMAINS})."}
            )
        # Reject what the normalization would otherwise drop silently: a 200 with the
        # domain quietly missing is worse than a 400 naming it.
        invalid = domainnames.invalid_domains(value)
        if invalid:
            raise serializers.ValidationError(
                {field: f"Not valid domain name(s): {', '.join(invalid)}."}
            )
        return domainnames.normalize_domains(value)

    @staticmethod
    def _clean_website(value, domains):
        """Validate the per-domain website configuration against the declared domains.

        Returns one entry per declared domain, falling back to the domain's default
        mode for the ones the payload doesn't mention.
        """
        field = domains_service.WEBSITE_KEY
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                {field: "Must be an object keyed by domain name."}
            )

        unknown = sorted(set(value) - set(domains))
        if unknown:
            raise serializers.ValidationError(
                {
                    field: (
                        f"Domain(s) {', '.join(unknown)} are not declared "
                        f"for this organization."
                    )
                }
            )

        website = {}
        for domain in domains:
            entry = value.get(domain)
            default = domains_service.default_mode(domain)
            if entry is None:
                website[domain] = {"mode": default}
                continue
            if not isinstance(entry, dict):
                raise serializers.ValidationError(
                    {field: f"{domain}: must be an object with a 'mode'."}
                )
            mode = entry.get("mode", default)
            if mode not in domains_service.WEBSITE_MODES:
                raise serializers.ValidationError(
                    {
                        field: (
                            f"{domain}: unknown mode '{mode}'. Valid modes: "
                            f"{', '.join(domains_service.WEBSITE_MODES)}."
                        )
                    }
                )
            # A collectivité's website — our parking page or its own server — is
            # only served on an RPNT 1.2 conformant extension. Anything else may
            # redirect to the official domain, or serve nothing.
            allowed = domains_service.allowed_modes(domain)
            if mode not in allowed:
                raise serializers.ValidationError(
                    {
                        field: (
                            f"{domain}: mode '{mode}' requires an RPNT 1.2 "
                            f"conformant extension "
                            f"({', '.join(sorted(domains_service.DOMAIN_EXTENSIONS_ALLOWED))}). "
                            f"Valid modes for this domain: {', '.join(allowed)}."
                        )
                    }
                )
            if mode not in domains_service.MODES_WITH_TARGET:
                website[domain] = {"mode": mode}
                continue
            # A mode without a usable target would silently fall back to the default
            # mode on read; refuse it instead.
            target = entry.get("target")
            if not domains_service.is_valid_target(mode, target):
                if mode == domains_service.MODE_DNS_A:
                    expected = (
                        f"up to {domains_service.MAX_ADDRESSES} IPv4/IPv6 "
                        f"addresses separated by commas"
                    )
                elif mode == domains_service.MODE_DNS_CNAME:
                    expected = "a domain name"
                else:
                    expected = "an https url"
                raise serializers.ValidationError(
                    {field: f"{domain}: mode '{mode}' requires {expected} as target."}
                )
            website[domain] = {
                "mode": mode,
                "target": domains_service.normalize_target(mode, target),
            }
        return website

    def _validate_domains_subscription(self, attrs):
        """Validate the ``domains`` service metadata (declared domains + website).

        Domains are normalized, the website configuration is restricted to declared
        domains (with a validated target for the DNS modes), and an active
        subscription owns its domains exclusively: a domain can only have one
        organization behind it.
        """
        if self._get_service_type() != domains_service.SERVICE_TYPE:
            return

        instance = self.instance
        existing_metadata = (instance.metadata if instance else {}) or {}
        new_metadata = attrs.get("metadata") or {}

        domains = self._clean_domain_list(
            new_metadata.get(
                domains_service.DOMAINS_KEY,
                existing_metadata.get(domains_service.DOMAINS_KEY, []),
            ),
            domains_service.DOMAINS_KEY,
        )
        if domains_service.WEBSITE_KEY in new_metadata:
            website_value = new_metadata[domains_service.WEBSITE_KEY]
        else:
            # Keep what is stored, minus the domains that have since been removed:
            # the caller didn't send that config, so don't reject the request over it.
            stored = existing_metadata.get(domains_service.WEBSITE_KEY) or {}
            website_value = (
                {d: entry for d, entry in stored.items() if d in domains}
                if isinstance(stored, dict)
                else {}
            )
        website = self._clean_website(website_value, domains)

        is_active = attrs.get("is_active", instance.is_active if instance else True)
        if domains and is_active:
            self._check_domains_not_claimed(domains)

        # Merge so metadata keys we don't own are preserved, and store the
        # normalized values (this also normalizes on an is_active-only PATCH).
        attrs["metadata"] = {
            **existing_metadata,
            **new_metadata,
            domains_service.DOMAINS_KEY: domains,
            domains_service.WEBSITE_KEY: website,
        }

    def _check_domains_not_claimed(self, domains):
        """Refuse domains already declared on another active domains subscription."""
        # Lock the domains first: select_for_update can only lock rows that already
        # exist, so without this two transactions claiming the same new domain both
        # see "no conflict". Held until the view transaction commits.
        locks.lock_domains(domains)

        overlap_q = Q()
        for domain in domains:
            overlap_q |= Q(metadata__domains__contains=[domain])

        conflicting = (
            models.ServiceSubscription.objects.filter(
                overlap_q,
                service__type=domains_service.SERVICE_TYPE,
                is_active=True,
            )
            .select_for_update()
            .exclude(pk=self.instance.pk if self.instance else None)
            .values_list("metadata", flat=True)
        )

        overlap = set()
        for metadata in conflicting:
            overlap |= set(
                domainnames.normalize_domains(
                    (metadata or {}).get(domains_service.DOMAINS_KEY)
                )
            ) & set(domains)

        if overlap:
            raise serializers.ValidationError(
                {
                    domains_service.DOMAINS_KEY: (
                        f"Domain(s) {', '.join(sorted(overlap))} are already "
                        f"declared by another organization."
                    )
                }
            )

    def _is_superuser(self):
        """Check if the current request user is a superuser."""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return getattr(request.user, "is_superuser", False)
        return False

    def _get_organization(self):
        """Resolve the organization from instance or view kwargs."""
        if self.instance:
            return self.instance.organization

        view = self.context.get("view")
        if view and "organization_id" in getattr(view, "kwargs", {}):
            return models.Organization.objects.filter(
                id=view.kwargs["organization_id"]
            ).first()
        return None

    def _validate_extended_admin_subscription(
        self, attrs, service_type, existing_metadata
    ):
        """
        Validate extended admin subscription data (ADC/ESD services).
        Validates auto_admin metadata value and merges it with existing metadata.
        """
        resolver_class = TYPE_TO_ADMIN_RESOLVER.get(service_type)
        if not resolver_class or not issubclass(
            resolver_class, ExtendedAdminEntitlementResolver
        ):
            return

        new_metadata = attrs.get("metadata")
        if not new_metadata or "auto_admin" not in new_metadata:
            return

        auto_admin = new_metadata["auto_admin"]
        if auto_admin not in self.VALID_AUTO_ADMIN_VALUES:
            raise serializers.ValidationError(
                {
                    "metadata": (
                        f"Invalid auto_admin value: '{auto_admin}'. "
                        f"Must be one of: {', '.join(self.VALID_AUTO_ADMIN_VALUES)}."
                    )
                }
            )

        # Merge auto_admin into existing metadata, preserving other keys
        merged_metadata = dict(existing_metadata or {})
        merged_metadata["auto_admin"] = auto_admin
        attrs["metadata"] = merged_metadata

    def _get_service(self):
        """Resolve the service from instance or view kwargs."""
        if self.instance:
            return self.instance.service

        view = self.context.get("view")
        if view and "service_id" in getattr(view, "kwargs", {}):
            try:
                return models.Service.objects.get(id=view.kwargs["service_id"])
            except models.Service.DoesNotExist:
                return None
        return None

    def _get_service_type(self):
        """Resolve the service type from instance or view kwargs."""
        service = self._get_service()
        return service.type if service else None

    def validate(self, attrs):
        """Validate subscription data."""
        instance = self.instance

        # DRF's JSONField accepts any JSON value, so "metadata" can arrive as a
        # string/number/list. Every per-service validator below reads it with
        # .get()/in and would raise AttributeError/TypeError on those — a 500 on
        # attacker-controlled shape. Reject the shape once, here, rather than
        # guarding three call sites.
        if "metadata" in attrs and not isinstance(attrs["metadata"], dict):
            raise serializers.ValidationError(
                {"metadata": "Must be an object keyed by metadata name."}
            )

        self._validate_proconnect_subscription(attrs)
        self._validate_domains_subscription(attrs)

        service = self._get_service()
        if service:
            existing_metadata = instance.metadata if instance else {}
            self._validate_extended_admin_subscription(
                attrs, service.type, existing_metadata
            )
        # Validate entitlement types here (at is_valid time) so an invalid type is
        # rejected before the subscription is saved — otherwise the save's
        # ProConnect push would fire and then get rolled back, drifting the provider.
        self._validate_entitlement_types(service)

        return attrs


class SubscriptionWithOperatorSerializer(ServiceSubscriptionSerializer):
    """
    Serialize service subscriptions with operator info.
    Used when returning subscription data that may be from another operator.
    """

    operator_id = serializers.UUIDField(source="operator.id", read_only=True)
    operator_name = serializers.CharField(source="operator.name", read_only=True)

    class Meta:
        model = models.ServiceSubscription
        fields = ServiceSubscriptionSerializer.Meta.fields + [
            "operator_id",
            "operator_name",
        ]
        read_only_fields = ServiceSubscriptionSerializer.Meta.read_only_fields + [
            "operator_id",
            "operator_name",
        ]


class ServiceSubscriptionWithServiceSerializer(ServiceSubscriptionSerializer):
    """Serialize service subscriptions with the service."""

    service = ServiceSerializer(read_only=True)

    operator = OperatorSerializer(read_only=True)

    class Meta:
        model = models.ServiceSubscription
        fields = ServiceSubscriptionSerializer.Meta.fields + ["service", "operator"]
        read_only_fields = [field for field in fields if field != "metadata"]


class ProConnectDomainsSerializer(serializers.Serializer):
    """The normalized domain buckets returned by the ``proconnect-domains`` action.

    Documentation/schema only — the action returns the dict built by the service
    layer, not a serialized model.
    """

    requested = serializers.ListField(child=serializers.CharField())
    manual = serializers.ListField(child=serializers.CharField())
    dpnt = serializers.ListField(child=serializers.CharField())
    candidates = serializers.ListField(child=serializers.CharField())
    discarded = serializers.ListField(child=serializers.CharField())

    def create(self, validated_data):
        raise NotImplementedError

    def update(self, instance, validated_data):
        raise NotImplementedError


class ProConnectDomainsUpdateSerializer(serializers.Serializer):
    """Body of the ``proconnect-domains`` PATCH action.

    Documentation/schema only — the action validates and normalizes the buckets
    itself (each key is optional; an omitted bucket is left untouched).
    """

    manual = serializers.ListField(child=serializers.CharField(), required=False)
    requested = serializers.ListField(child=serializers.CharField(), required=False)
    discarded = serializers.ListField(child=serializers.CharField(), required=False)

    def create(self, validated_data):
        raise NotImplementedError

    def update(self, instance, validated_data):
        raise NotImplementedError


class OrganizationSerializer(serializers.ModelSerializer):
    """Serialize organizations."""

    service_subscriptions = ServiceSubscriptionWithServiceSerializer(
        many=True, read_only=True
    )
    # The raw buckets, plus the two derived views the UI needs. Both are computed
    # here so the routable rule and the pre-validation verdict are never restated
    # in the frontend.
    proconnect_domains = serializers.SerializerMethodField(read_only=True)
    proconnect_routable = serializers.SerializerMethodField(read_only=True)
    proconnect_prevalidated = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Organization
        fields = [
            "id",
            "name",
            "type",
            "siret",
            "siren",
            "code_postal",
            "code_insee",
            "population",
            "epci_libelle",
            "epci_siren",
            "epci_population",
            "departement_code_insee",
            "region_code_insee",
            "adresse_messagerie",
            "site_internet",
            "telephone",
            "rpnt",
            "service_public_url",
            "proconnect_domains",
            "proconnect_routable",
            "proconnect_prevalidated",
            "service_subscriptions",
        ]
        read_only_fields = fields

    @extend_schema_field(
        {
            "type": "object",
            "description": (
                "The org's ProConnect domains by provenance (dpnt/candidates/manual) "
                "and status (requested/discarded)."
            ),
            "properties": {
                bucket: {"type": "array", "items": {"type": "string"}}
                for bucket in proconnect_service.PROCONNECT_DOMAIN_BUCKETS
            },
        }
    )
    def get_proconnect_domains(self, instance):
        """The normalized buckets, as stored."""
        return proconnect_service.proconnect_domains(instance)

    @extend_schema_field(
        {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "The domains the org may route to a ProConnect provider — the "
                "buckets with the discard rules applied. The UI offers exactly these."
            ),
        }
    )
    def get_proconnect_routable(self, instance):
        """The routable set (see ``core.services.proconnect.domain_provenances``).

        Org-wide: an org can have several ProConnect services, and this payload is
        not about one of them, so "live" here means live on any of its providers.
        Routing the same domain to two providers is refused on write anyway.
        """
        return proconnect_service.routable_domains(instance)

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
            "description": (
                "Per operator idp, the org domains already in the deployed allowlist "
                "(empty for an idp the allowlist does not cover). Null when no "
                "allowlist has been fetched at all (pre-validation unknown)."
            ),
        }
    )
    def get_proconnect_prevalidated(self, instance):
        """The subset of the org's domains already in the *deployed* allowlist.

        From the cache filled by ``proconnect_fetch_prevalidated``. Null means no
        allowlist has been fetched, which the UI shows as unknown rather than as
        "not pre-validated"; once one has, every idp gets a verdict.
        """
        return proconnect_service.prevalidated_org_domains(
            instance, self.context.get("proconnect_prevalidated_allowlists")
        )

    def to_representation(self, instance):
        """Convert the representation to the desired format."""
        data = super().to_representation(instance)
        mail_domain, mail_domain_status = instance.get_mail_domain_status()
        data["mail_domain"] = mail_domain
        data["mail_domain_status"] = mail_domain_status

        # Expose the operator_admins_have_admin_role flag from the
        # OperatorOrganizationRole for the current operator context.
        # Uses prefetched_operator_roles when available (set by viewset)
        # to avoid N+1 queries on list endpoints.
        prefetched = getattr(instance, "prefetched_operator_roles", None)
        if prefetched is not None:
            role = prefetched[0] if prefetched else None
            data["operator_admins_have_admin_role"] = (
                role.operator_admins_have_admin_role if role else False
            )
        else:
            view = self.context.get("view")
            operator_id = getattr(view, "kwargs", {}).get("operator_id")
            if operator_id:
                role = instance.operator_roles.filter(operator_id=operator_id).first()
                data["operator_admins_have_admin_role"] = (
                    role.operator_admins_have_admin_role if role else False
                )

        return data


class OrganizationServiceSerializer(ServiceSerializer):
    """Serialize services for an organization. It contains the subscription for the given organization."""

    subscription = serializers.SerializerMethodField(read_only=True)
    operator_config = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Service
        fields = ServiceSerializer.Meta.fields + [
            "subscription",
            "operator_config",
        ]
        read_only_fields = fields

    def get_subscription(self, obj):
        """
        Return the effective subscription for this service.
        Priority:
        1. Current operator's subscription (if exists)
        2. Another operator's subscription (if exists, read-only)

        Always includes operator_id and operator_name to identify who owns the subscription.
        """
        # First try current operator's subscription (from prefetch)
        first_subscription = obj.subscriptions.first()
        if first_subscription:
            return SubscriptionWithOperatorSerializer(first_subscription).data

        # Fall back to other operator's subscription
        if hasattr(obj, "other_operator_subscription_prefetched"):
            other_subs = obj.other_operator_subscription_prefetched
            if other_subs:
                return SubscriptionWithOperatorSerializer(other_subs[0]).data

        return None

    def get_config(self, obj):
        """Get the effective configuration for the service, with operator overrides."""
        operator_id = self.context.get("operator_id")
        config = models.OperatorServiceConfig.get_effective_service_config(
            obj,
            models.Operator.objects.filter(id=operator_id).first()
            if operator_id
            else None,
        )
        whitelist_keys = [
            "help_center_url",
            "population_limits",
            "auto_admin_population_threshold",
            "idp_id",
        ]
        return {key: config[key] for key in whitelist_keys if key in config}

    def get_operator_config(self, obj):
        """Return operator configuration for this service."""

        configs = obj.operatorserviceconfig_set.all()
        if configs.count() > 0:
            return {
                "display_priority": configs[0].display_priority,
                "externally_managed": configs[0].externally_managed,
            }
        return None

    def to_representation(self, instance):
        """Convert the representation to the desired format."""
        data = super().to_representation(instance)
        if "organization" not in self.context:
            raise ValueError(
                "OrganizationServiceSerializer requires 'organization' in context"
            )

        organization = self.context["organization"]
        operator = None
        if "operator_id" in self.context:
            try:
                operator = models.Operator.objects.get(id=self.context["operator_id"])
            except models.Operator.DoesNotExist:
                pass

        can_activate, reason = instance.can_activate(organization, operator)
        data["can_activate"] = can_activate
        if not can_activate and reason:
            data["activation_blocked_reason"] = reason
        return data


class AccountSerializer(serializers.ModelSerializer):
    """Serialize accounts."""

    service_links = serializers.SerializerMethodField()
    roles = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )

    class Meta:
        model = models.Account
        fields = ["id", "email", "external_id", "type", "roles", "service_links"]
        read_only_fields = ["id", "service_links"]

    def get_service_links(self, obj):
        """Aggregate one-row-per-role into dict format grouped by service.

        Expects service_links and service_links__service to be prefetched
        (see OrganizationAccountsViewSet.get_queryset).
        """
        by_service = defaultdict(lambda: {"roles": {}, "service": None})
        for link in obj.service_links.all():
            entry = by_service[link.service_id]
            if entry["service"] is None:
                entry["service"] = {
                    "id": link.service.id,
                    "name": link.service.name,
                    "instance_name": link.service.instance_name,
                    "type": link.service.type,
                }
            entry["roles"][link.role] = {"scope": link.scope or {}}
        return list(by_service.values())
