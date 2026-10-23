"""Tests for the admin page that subscribes every organization of an operator."""

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

import pytest

from core import factories, models
from core.services import domains as domains_service

pytestmark = pytest.mark.django_db

URL = "/admin/core/servicesubscription/bulk-operator-subscribe/"


def _admin_client(**user_kwargs):
    user = factories.UserFactory(
        **{"is_staff": True, "is_superuser": True, **user_kwargs}
    )
    client = Client()
    client.force_login(user)
    return client


def _setup(managed=3, service_kwargs=None):
    """An operator managing ``managed`` organizations, and a service it offers."""
    operator = factories.OperatorFactory()
    organizations = factories.OrganizationFactory.create_batch(managed)
    for organization in organizations:
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization
        )
    service = factories.ServiceFactory(**(service_kwargs or {}))
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    return operator, organizations, service


def _data(operator, service, **overrides):
    return {
        "operator": str(operator.pk),
        "service": str(service.pk),
        "is_active": "on",
        "metadata": "{}",
        **overrides,
    }


def _subscribe(client, operator, service, **overrides):
    """Preview, then confirm, as the page does."""
    return client.post(URL, {**_data(operator, service, **overrides), "confirm": "1"})


def test_changelist_links_to_the_page():
    """The subscriptions list has a button to the page."""
    response = _admin_client().get(reverse("admin:core_servicesubscription_changelist"))

    assert response.status_code == 200
    assert URL in response.content.decode()
    assert "Bulk operator subscription" in response.content.decode()


def test_the_page_renders():
    """The form has the reassign option and the metadata field."""
    response = _admin_client().get(URL)

    assert response.status_code == 200
    content = response.content.decode()
    assert "reassign_existing" in content
    assert 'name="metadata"' in content


def test_a_first_submit_only_previews():
    """Nothing is written before the summary is confirmed."""
    operator, organizations, service = _setup(managed=3)
    factories.OrganizationFactory()  # not managed by the operator
    factories.ServiceSubscriptionFactory(
        organization=organizations[0], service=service, operator=operator
    )

    response = _admin_client().post(URL, _data(operator, service))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<strong>2</strong>" in content  # to subscribe
    assert 'name="confirm"' in content
    assert models.ServiceSubscription.objects.filter(service=service).count() == 1


def test_confirming_subscribes_the_organizations_the_operator_manages():
    """Managed organizations get a subscription, with the metadata, and only they."""
    operator, organizations, service = _setup(managed=3)
    outsider = factories.OrganizationFactory()

    response = _subscribe(
        _admin_client(), operator, service, metadata='{"plan": "free"}'
    )

    assert response.status_code == 302
    subscriptions = models.ServiceSubscription.objects.filter(service=service)
    assert {s.organization_id for s in subscriptions} == {o.pk for o in organizations}
    assert not subscriptions.filter(organization=outsider).exists()
    assert all(s.operator == operator and s.is_active for s in subscriptions)
    assert all(s.metadata == {"plan": "free"} for s in subscriptions)


def test_the_subscriptions_can_be_created_inactive():
    """Unchecking the active box creates inactive subscriptions."""
    operator, _organizations, service = _setup(managed=2)

    _subscribe(_admin_client(), operator, service, is_active="")

    subscriptions = models.ServiceSubscription.objects.filter(service=service)
    assert subscriptions.count() == 2
    assert not subscriptions.filter(is_active=True).exists()


def test_the_default_entitlements_are_created():
    """Rows are saved as any subscription is, so the service handler runs."""
    operator, organizations, service = _setup(
        managed=1, service_kwargs={"type": "drive"}
    )

    _subscribe(_admin_client(), operator, service)

    subscription = models.ServiceSubscription.objects.get(
        service=service, organization=organizations[0]
    )
    assert subscription.entitlements.count() == 2


def test_an_existing_subscription_of_another_operator_is_left_alone():
    """Without the reassign box, another operator's subscription is not touched."""
    operator, organizations, service = _setup(managed=2)
    other = factories.OperatorFactory()
    held = factories.ServiceSubscriptionFactory(
        organization=organizations[0],
        service=service,
        operator=other,
        is_active=False,
        metadata={"keep": "me"},
    )

    _subscribe(_admin_client(), operator, service)

    held.refresh_from_db()
    assert held.operator == other
    assert models.ServiceSubscription.objects.filter(service=service).count() == 2


def test_reassigning_moves_the_subscriptions_of_other_operators():
    """With the reassign box, managed organizations' subscriptions change operator."""
    operator, organizations, service = _setup(managed=2)
    other = factories.OperatorFactory()
    held = factories.ServiceSubscriptionFactory(
        organization=organizations[0],
        service=service,
        operator=other,
        is_active=False,
        metadata={"keep": "me"},
    )
    outsider = factories.ServiceSubscriptionFactory(
        organization=factories.OrganizationFactory(), service=service, operator=other
    )

    _subscribe(_admin_client(), operator, service, reassign_existing="on")

    held.refresh_from_db()
    assert held.operator == operator
    # Moved as it was: the page decides the operator, not the state.
    assert held.is_active is False
    assert held.metadata == {"keep": "me"}
    assert models.ServiceSubscription.objects.filter(service=service).count() == 3
    # An organization the operator does not manage stays with its operator.
    outsider.refresh_from_db()
    assert outsider.operator == other


def test_the_result_counts_the_rows_left_with_another_operator():
    """A refused reassignment stays with its operator, and is counted as such."""
    operator, organizations, service = _setup(
        managed=2, service_kwargs={"config": {"population_limits": {"commune": 1000}}}
    )
    other = factories.OperatorFactory()
    for organization in organizations:
        organization.type = "commune"
        organization.population = 100
        organization.epci_population = None
        organization.save()
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service, operator=other
        )
    big = organizations[0]
    big.population = 50000
    big.save()

    response = _admin_client().post(
        URL,
        {**_data(operator, service, reassign_existing="on"), "confirm": "1"},
        follow=True,
    )

    assert "1 reassigned, 0 already belonged to this operator, 1 left" in (
        response.content.decode()
    )
    big_subscription = models.ServiceSubscription.objects.get(
        service=service, organization=big
    )
    assert big_subscription.operator == other


def test_the_left_count_is_the_whole_set_without_reassigning():
    """Without the reassign box, every row of another operator is left."""
    operator, organizations, service = _setup(managed=2)
    other = factories.OperatorFactory()
    for organization in organizations:
        factories.ServiceSubscriptionFactory(
            organization=organization, service=service, operator=other
        )

    response = _admin_client().post(
        URL, {**_data(operator, service), "confirm": "1"}, follow=True
    )

    assert "0 reassigned, 0 already belonged to this operator, 2 left" in (
        response.content.decode()
    )


def test_a_proconnect_subscription_cannot_be_created_active_in_bulk():
    """As in the API, ProConnect is only active with a domain: it is created inactive."""
    operator, _organizations, service = _setup(
        managed=2, service_kwargs={"type": "proconnect"}
    )
    client = _admin_client()

    refused = _subscribe(client, operator, service)
    assert refused.status_code == 200
    assert "needs a domain to be active" in refused.content.decode()
    assert not models.ServiceSubscription.objects.filter(service=service).exists()

    _subscribe(client, operator, service, is_active="")
    assert models.ServiceSubscription.objects.filter(service=service).count() == 2


def test_the_changelist_link_needs_the_permission_of_the_page():
    """A staff user who would get a 403 on the page is not shown the button."""
    changelist = reverse("admin:core_servicesubscription_changelist")
    user = factories.UserFactory(is_staff=True, is_superuser=False)
    user.user_permissions.add(
        Permission.objects.get(codename="view_servicesubscription")
    )
    client = Client()
    client.force_login(user)

    response = client.get(changelist)

    assert response.status_code == 200
    assert URL not in response.content.decode()


def test_a_service_the_operator_does_not_offer_is_refused():
    """As in the API, the service must be configured for the operator."""
    operator, _organizations, _service = _setup(managed=2)
    unavailable = factories.ServiceFactory()

    response = _subscribe(_admin_client(), operator, unavailable)

    assert response.status_code == 200
    assert "not available for this operator" in response.content.decode()
    assert not models.ServiceSubscription.objects.filter(service=unavailable).exists()


@pytest.mark.parametrize("service_type", ["domains", "proconnect"])
def test_domains_cannot_be_set_in_bulk(service_type):
    """One domain list copied to every organization would claim it many times."""
    operator, _organizations, service = _setup(
        managed=2, service_kwargs={"type": service_type}
    )

    response = _subscribe(
        _admin_client(), operator, service, metadata='{"domains": ["a.fr"]}'
    )

    assert response.status_code == 200
    assert "exclusive" in response.content.decode()
    assert not models.ServiceSubscription.objects.filter(service=service).exists()


@pytest.mark.parametrize("metadata", ["{not json", "[1, 2]"])
def test_metadata_must_be_a_json_object(metadata):
    """Broken JSON, or JSON that is not an object, is refused."""
    operator, _organizations, service = _setup(managed=1)

    response = _subscribe(_admin_client(), operator, service, metadata=metadata)

    assert response.status_code == 200
    assert not models.ServiceSubscription.objects.filter(service=service).exists()


def test_a_refused_row_does_not_stop_the_others():
    """Activating is validated as for any subscription: a population limit refuses
    that organization only, and the page says so."""
    operator, organizations, service = _setup(
        managed=3, service_kwargs={"config": {"population_limits": {"commune": 1000}}}
    )
    for organization in organizations:
        organization.type = "commune"
        organization.population = 100
        organization.epci_population = None
        organization.save()
    big = organizations[0]
    big.population = 50000
    big.save()

    response = _admin_client().post(
        URL, {**_data(operator, service), "confirm": "1"}, follow=True
    )

    subscribed = set(
        models.ServiceSubscription.objects.filter(service=service).values_list(
            "organization_id", flat=True
        )
    )
    assert subscribed == {organizations[1].pk, organizations[2].pk}
    content = response.content.decode()
    assert "2 created" in content
    assert big.name in content
    assert "population_limit_exceeded" in content


def test_the_result_is_logged_on_the_operator():
    """The operator's history says what was done and for which service."""
    operator, _organizations, service = _setup(managed=2)

    _subscribe(_admin_client(), operator, service)

    entry = LogEntry.objects.get(object_id=str(operator.pk))
    assert "2 created" in entry.change_message
    assert service.name in entry.change_message


def test_a_staff_user_without_permission_is_refused():
    """The page needs the permission to add and change subscriptions."""
    operator, _organizations, service = _setup(managed=1)
    client = _admin_client(is_superuser=False)

    assert client.get(URL).status_code == 403
    assert _subscribe(client, operator, service).status_code == 403
    assert not models.ServiceSubscription.objects.filter(service=service).exists()


def test_domains_service_parks_the_dila_domains_of_bulk_subscribed_organizations():
    """A bulk subscription declares no domain, so the export proposes a parking page
    for the domains the organization declared at DILA, and for nothing else."""
    operator, organizations, service = _setup(
        managed=3, service_kwargs={"type": domains_service.SERVICE_TYPE}
    )
    organizations[0].proconnect_domains = {"dpnt": ["commune-exemple.fr"]}
    organizations[0].save()

    _subscribe(_admin_client(), operator, service)

    assert models.ServiceSubscription.objects.filter(service=service).count() == 3
    exported = domains_service.export_domains()
    assert [(e["domain"], e["source"]) for e in exported] == [
        ("commune-exemple.fr", "dpnt")
    ]
    assert exported[0]["website"] == {"mode": "parking"}

    # A domain the organization declares itself replaces the proposal.
    subscription = models.ServiceSubscription.objects.get(
        service=service, organization=organizations[0]
    )
    subscription.metadata = {"domains": ["autre-exemple.fr"]}
    subscription.save()
    exported = domains_service.export_domains()
    assert [(e["domain"], e["source"]) for e in exported] == [
        ("autre-exemple.fr", "subscription")
    ]
