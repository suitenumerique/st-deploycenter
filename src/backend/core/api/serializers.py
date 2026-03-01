"""Client serializers for the deploycenter core app."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models
from core.entitlements.resolvers import TYPE_TO_ADMIN_RESOLVER
from core.entitlements.resolvers.extended_admin_entitlement_resolver import (
    ExtendedAdminEntitlementResolver,
)
from core.services import get_service_handler


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


class UserField(serializers.PrimaryKeyRelatedField):
    """Custom field that accepts either UUID or email address for user lookup."""

    def to_internal_value(self, data):
        """Convert UUID string or email to User instance."""
        if isinstance(data, str):
            if "@" in data:
                # It's an email address, look up the user
                try:
                    return models.User.objects.get(email=data)
                except models.User.DoesNotExist as e:
                    raise serializers.ValidationError(
                        f"No user found with email: {data}"
                    ) from e
            else:
                # It's a UUID, use the parent method
                return super().to_internal_value(data)
        return super().to_internal_value(data)


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
        fields = ["id", "name", "url", "is_active", "user_role", "config"]
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
        # Work on a shallow copy to avoid mutating the original input
        data = {**data}
        # Pop the entitlements from input data to handle separately
        entitlements_data = data.pop("entitlements", None)
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

    def apply_entitlement_configs(self, subscription):
        """Apply pending entitlement configs to the subscription.

        Only updates default entitlements (where account=None).
        Account-specific entitlements are never modified by this method.
        Validates that entitlement types are appropriate for the service.
        """
        if not self._pending_entitlement_configs:
            return

        # Get valid entitlement types for this service
        handler = get_service_handler(subscription.service)
        valid_types = set()
        if handler:
            valid_types = {d["type"] for d in handler.get_default_entitlements()}

        for config_data in self._pending_entitlement_configs:
            entitlement_type = config_data["type"]
            account_type = config_data["account_type"]
            config = config_data["config"]

            # Validate entitlement type is appropriate for this service
            # Only validate if the service has defined valid types (via handler)
            if valid_types and entitlement_type not in valid_types:
                raise serializers.ValidationError(
                    {
                        "entitlements": f"Entitlement type '{entitlement_type}' is not valid "
                        f"for service type '{subscription.service.type}'. "
                        f"Valid types: {', '.join(str(t) for t in valid_types)}"
                    }
                )

            # Also validate the type is a valid EntitlementType enum value
            valid_enum_types = [t.value for t in models.Entitlement.EntitlementType]
            if entitlement_type not in valid_enum_types:
                raise serializers.ValidationError(
                    {
                        "entitlements": f"Unknown entitlement type '{entitlement_type}'. "
                        f"Valid types: {', '.join(valid_enum_types)}"
                    }
                )

            # Only update default entitlements (account=None), never account-specific ones
            # Use update_or_create for atomic operation
            subscription.entitlements.update_or_create(
                type=entitlement_type,
                account_type=account_type,
                account=None,
                defaults={"config": config},
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

        current_metadata = instance.metadata if instance else {}
        is_active = attrs.get("is_active", instance.is_active if instance else True)

        mail_domain = organization.mail_domain if organization else None
        existing_domains = current_metadata.get("domains")
        superuser_domains = attrs.get("metadata", {}).get("domains")

        # Superusers can override domains
        if self._is_superuser() and isinstance(superuser_domains, list):
            resolved_domains = superuser_domains
        else:
            resolved_domains = existing_domains or (
                [mail_domain] if mail_domain else []
            )

        # When activating a subscription, we must have a valid domain.
        if is_active and not resolved_domains:
            raise serializers.ValidationError(
                {"metadata": "Mail domain is required for ProConnect subscription."}
            )

        # Domain uniqueness: no two active ProConnect subscriptions may share
        # a domain (across all organizations and operators).
        if resolved_domains and is_active:
            current_sub_id = instance.pk if instance else None
            other_subs = models.ServiceSubscription.objects.filter(
                service__type="proconnect",
                is_active=True,
            ).exclude(pk=current_sub_id)
            for sub in other_subs:
                overlap = set(sub.metadata.get("domains", [])) & set(resolved_domains)
                if overlap:
                    raise serializers.ValidationError(
                        {
                            "metadata": (
                                f"Domain(s) {', '.join(sorted(overlap))} already used "
                                f"by another active ProConnect subscription."
                            )
                        }
                    )

        # Build the metadata dict explicitly
        attrs["metadata"] = {
            "domains": resolved_domains,
        }

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

        self._validate_proconnect_subscription(attrs)

        service_type = self._get_service_type()
        if service_type:
            existing_metadata = instance.metadata if instance else {}
            self._validate_extended_admin_subscription(
                attrs, service_type, existing_metadata
            )

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


class OrganizationSerializer(serializers.ModelSerializer):
    """Serialize organizations."""

    service_subscriptions = ServiceSubscriptionWithServiceSerializer(
        many=True, read_only=True
    )

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
            "service_subscriptions",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        """Convert the representation to the desired format."""
        data = super().to_representation(instance)
        mail_domain, mail_domain_status = instance.get_mail_domain_status()
        data["mail_domain"] = mail_domain
        data["mail_domain_status"] = mail_domain_status
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


class AccountServiceLinkSerializer(serializers.ModelSerializer):
    """Serialize account service links."""

    service = ServiceLightSerializer(read_only=True)
    roles = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )

    class Meta:
        model = models.AccountServiceLink
        fields = ["roles", "scope", "service"]


class AccountSerializer(serializers.ModelSerializer):
    """Serialize accounts."""

    service_links = AccountServiceLinkSerializer(
        many=True,
        read_only=True,
    )
    roles = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )

    class Meta:
        model = models.Account
        fields = ["id", "email", "external_id", "type", "roles", "service_links"]
        read_only_fields = ["id", "service_links"]
