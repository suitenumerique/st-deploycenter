"""Client serializers for the deploycenter core app."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models


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
        fields = ["id", "email", "full_name", "language"]
        read_only_fields = ["id", "email", "full_name"]


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
        whitelist_keys = ["idps"]
        return {key: config[key] for key in whitelist_keys if key in config}


class ServiceSerializer(serializers.ModelSerializer):
    """Serialize services."""

    logo = serializers.CharField(source="get_logo_url", read_only=True)
    config = serializers.SerializerMethodField(read_only=True)

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
        ]
        read_only_fields = fields

    def get_config(self, obj):
        """Get the configuration for the service."""
        config = obj.config or {}
        whitelist_keys = ["help_center_url", "population_limits"]
        return {key: config[key] for key in whitelist_keys if key in config}


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


class ServiceSubscriptionSerializer(serializers.ModelSerializer):
    """Serialize service subscriptions."""

    entitlements = EntitlementSerializer(many=True, read_only=True)

    class Meta:
        model = models.ServiceSubscription
        fields = ["metadata", "created_at", "updated_at", "is_active", "entitlements"]
        read_only_fields = ["created_at", "updated_at"]

    def _validate_proconnect_subscription(self, instance, attrs):
        """
        Validate ProConnect subscription data.
        It is not possible to update the IDP for an active ProConnect subscription.
        Deactivate the subscription first to change the IDP.
        """
        if instance.service.type != "proconnect":
            return

        is_active = attrs.get("is_active", instance.is_active)
        current_idp_id = instance.metadata.get("idp_id")
        new_idp_id = attrs.get("metadata", {}).get("idp_id")

        # Are we changing an IDP while a subscription is active?
        if is_active and new_idp_id and current_idp_id != new_idp_id:
            raise serializers.ValidationError(
                {
                    "metadata": (
                        "Cannot update idp_id for an active ProConnect subscription. "
                        "Deactivate the subscription first to change the IDP."
                    )
                }
            )

        # When activating a subscription, we must have a valid domain.
        if is_active and not (
            instance.organization.mail_domain or instance.metadata.get("domains")
        ):
            raise serializers.ValidationError(
                {"metadata": "Mail domain is required for ProConnect subscription."}
            )

        # Build the metadata dict explicitly. Domains cannot be overridden from the REST API for now.
        attrs["metadata"] = {
            "idp_id": new_idp_id or current_idp_id,
            "domains": instance.metadata.get("domains", False)
            or [instance.organization.mail_domain],
        }

    def validate(self, attrs):
        """Validate subscription data."""
        instance = self.instance
        if instance:
            self._validate_proconnect_subscription(instance, attrs)

        return attrs


class OtherOperatorSubscriptionSerializer(serializers.Serializer):
    """Serialize subscription info from other operators (read-only)."""

    operator_id = serializers.UUIDField(source="operator.id")
    operator_name = serializers.CharField(source="operator.name")
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()

    def create(self, validated_data):
        """Not implemented - this serializer is read-only."""
        raise NotImplementedError("This serializer is read-only")

    def update(self, instance, validated_data):
        """Not implemented - this serializer is read-only."""
        raise NotImplementedError("This serializer is read-only")


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
    other_operator_subscription = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Service
        fields = ServiceSerializer.Meta.fields + [
            "subscription",
            "operator_config",
            "other_operator_subscription",
        ]
        read_only_fields = fields

    def get_subscription(self, obj):
        """
        Return only the first subscription if multiple exist.
        """
        first_subscription = obj.subscriptions.first()
        if first_subscription:
            return ServiceSubscriptionSerializer(first_subscription).data
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

    def get_other_operator_subscription(self, obj):
        """
        Return the subscription from another operator for this service and organization,
        or None. There can be at most one per (organization, service) due to unique_together.
        Uses prefetched data when available.
        """
        if "organization" not in self.context or "operator_id" not in self.context:
            return None

        # Use prefetched data if available (Prefetch to_attr returns a list)
        if hasattr(obj, "other_operator_subscription_prefetched"):
            other_subs = obj.other_operator_subscription_prefetched
        else:
            organization = self.context["organization"]
            current_operator_id = self.context["operator_id"]
            other_subs = list(
                models.ServiceSubscription.objects.filter(
                    organization=organization,
                    service=obj,
                )
                .exclude(operator_id=current_operator_id)
                .select_related("operator")
            )

        if other_subs:
            return OtherOperatorSubscriptionSerializer(other_subs[0]).data
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
        fields = ["roles", "service"]


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
