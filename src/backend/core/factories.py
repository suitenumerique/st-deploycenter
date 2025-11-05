"""
Core application factories
"""

from django.conf import settings
from django.contrib.auth.hashers import make_password

import factory.fuzzy
from faker import Faker

from core import models

fake = Faker()


class UserFactory(factory.django.DjangoModelFactory):
    """A factory to random users for testing purposes."""

    class Meta:
        model = models.User
        skip_postgeneration_save = True

    sub = factory.Sequence(lambda n: f"user{n!s}")
    email = factory.Faker("email")
    full_name = factory.Faker("name")
    language = factory.fuzzy.FuzzyChoice([lang[0] for lang in settings.LANGUAGES])
    password = make_password("password")


class ParentNodeFactory(factory.declarations.ParameteredAttribute):
    """Custom factory attribute for setting the parent node."""

    def generate(self, step, params):
        """
        Generate a parent node for the factory.

        This method is invoked during the factory's build process to determine the parent
        node of the current object being created. If `params` is provided, it uses the factory's
        metadata to recursively create or fetch the parent node. Otherwise, it returns `None`.
        """
        if not params:
            return None
        subfactory = step.builder.factory_meta.factory
        return step.recurse(subfactory, params)


class OperatorFactory(factory.django.DjangoModelFactory):
    """Factory for Operator model."""

    class Meta:
        model = models.Operator

    name = factory.Faker("company")
    url = factory.Faker("url")
    is_active = True


class UserOperatorRoleFactory(factory.django.DjangoModelFactory):
    """Factory for UserOperatorRole model."""

    class Meta:
        model = models.UserOperatorRole

    user = factory.SubFactory(UserFactory)
    operator = factory.SubFactory(OperatorFactory)
    role = "admin"


class OrganizationFactory(factory.django.DjangoModelFactory):
    """Factory for Organization model."""

    class Meta:
        model = models.Organization

    name = factory.Faker("city")
    type = "commune"
    siret = factory.Sequence(lambda n: f"{n:014d}")
    siren = factory.Sequence(lambda n: f"{n:09d}")
    code_insee = factory.Sequence(lambda n: f"{n:05d}")
    population = factory.Faker("random_int", min=1000, max=100000)
    code_postal = factory.Faker("postcode")
    epci_libelle = factory.Faker("city")
    epci_siren = factory.Sequence(lambda n: f"{n:09d}")
    epci_population = factory.Faker("random_int", min=5000, max=200000)
    departement_code_insee = factory.Sequence(
        lambda n: f"{(n % 95) + 1:02d}"
    )  # 1-95 for French departments
    region_code_insee = factory.Sequence(
        lambda n: f"{(n % 13) + 1:02d}"
    )  # 1-13 for French regions (excluding overseas)
    adresse_messagerie = factory.Faker("email")
    site_internet = factory.Faker("url")
    telephone = factory.LazyFunction(
        lambda: f"+33{fake.random_int(min=100000000, max=999999999)}"
    )
    rpnt = factory.Dict(
        {
            "criteria": ["accessibility", "transparency"],
            "score": factory.Faker("random_int", min=1, max=5),
        }
    )
    service_public_url = factory.Faker("url")


class OperatorOrganizationRoleFactory(factory.django.DjangoModelFactory):
    """Factory for OperatorOrganizationRole model."""

    class Meta:
        model = models.OperatorOrganizationRole

    operator = factory.SubFactory(OperatorFactory)
    organization = factory.SubFactory(OrganizationFactory)
    role = "admin"


class ServiceFactory(factory.django.DjangoModelFactory):
    """Factory for Service model."""

    class Meta:
        model = models.Service

    name = factory.Faker("word")
    type = factory.Faker("word")
    url = factory.Faker("url")
    description = factory.Faker("text", max_nb_chars=100)
    config = factory.Dict(
        {
            "metrics_endpoint": factory.Faker("url"),
            "metrics_auth_token": "test_token_123",
        }
    )
    is_active = True


class OperatorServiceConfigFactory(factory.django.DjangoModelFactory):
    """Factory for OperatorServiceConfig model."""

    class Meta:
        model = models.OperatorServiceConfig

    operator = factory.SubFactory(OperatorFactory)
    service = factory.SubFactory(ServiceFactory)
    display_priority = factory.Faker("random_int", min=1, max=100)


class ServiceSubscriptionFactory(factory.django.DjangoModelFactory):
    """Factory for ServiceSubscription model."""

    class Meta:
        model = models.ServiceSubscription

    organization = factory.SubFactory(OrganizationFactory)
    service = factory.SubFactory(ServiceFactory)
    metadata = factory.Dict(
        {"subscription_type": "standard", "notes": "Test subscription"}
    )


class MetricFactory(factory.django.DjangoModelFactory):
    """Factory for Metric model with unique constraint."""

    class Meta:
        model = models.Metric

    key = factory.Faker("word")
    value = factory.Faker("pydecimal", left_digits=5, right_digits=2, positive=True)
    service = factory.SubFactory(ServiceFactory)
    organization = factory.SubFactory(OrganizationFactory)
    timestamp = factory.Faker("date_time_this_year")


class EntitlementFactory(factory.django.DjangoModelFactory):
    """Factory for Entitlement model."""

    class Meta:
        model = models.Entitlement

    service_subscription = factory.SubFactory(ServiceSubscriptionFactory)
    type = models.Entitlement.EntitlementType.DRIVE_STORAGE
