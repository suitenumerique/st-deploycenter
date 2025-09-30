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
        fields = ["id", "email", "full_name"]
        read_only_fields = fields


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

class OperatorSerializer(serializers.ModelSerializer):
    """Serialize operators."""

    user_role = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Operator
        fields = ["id", "name", "url", "scope", "is_active", "user_role"]
        read_only_fields = fields

    def get_user_role(self, obj):
        roles = obj.user_roles.all()
        if roles.count() > 0:
            return roles[0].role
        return None


class OrganizationSerializer(serializers.ModelSerializer):
    """Serialize organizations."""

    class Meta:
        model = models.Organization
        fields = ["id", "name", "type", "siret", "siren", "code_postal", "code_insee", "population", "epci_libelle", "epci_siren", "epci_population", "departement_code_insee", "region_code_insee", "adresse_messagerie", "site_internet", "telephone", "rpnt", "service_public_url"]
        read_only_fields = fields