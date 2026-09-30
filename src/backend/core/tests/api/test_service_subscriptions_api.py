"""
Test the service subscriptions API, authenticated with Service subscriptions API keys.
"""
# pylint: disable=redefined-outer-name

from django.test import Client
from django.urls import reverse

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.api.viewsets import service_subscriptions

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    """A service with a subscriptions API key, an operator configured for it,
    managing an organization."""
    service = factories.ServiceFactory()
    key = service.generate_subscriptions_api_key()
    operator = factories.OperatorFactory(name="Operator", url="https://op.fr")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    return {
        "client": _client(key),
        "key": key,
        "service": service,
        "operator": operator,
        "organization": organization,
    }


def _client(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
    return client


def _list_url(service):
    return f"/api/v1.0/services/{service.id}/subscriptions/"


def _detail_url(service, subscription):
    return f"/api/v1.0/services/{service.id}/subscriptions/{subscription.id}/"


def _operators_url(service):
    return f"/api/v1.0/services/{service.id}/operators/"


def _create_body(setup, **overrides):
    return {
        "siret": setup["organization"].siret,
        "operator_id": str(setup["operator"].id),
        "is_active": True,
        **overrides,
    }


def _subscribe(setup, organization=None, **kwargs):
    return factories.ServiceSubscriptionFactory(
        organization=organization or setup["organization"],
        service=setup["service"],
        operator=setup["operator"],
        **kwargs,
    )


# --- Key lifecycle ---


def test_subscriptions_api_key_not_set_by_default():
    """A new service has no subscriptions API key."""
    assert factories.ServiceFactory().subscriptions_api_key_hash is None


def test_subscriptions_api_key_stored_hashed():
    """Only the SHA-256 of the key is stored."""
    service = factories.ServiceFactory()
    key = service.generate_subscriptions_api_key()
    service.refresh_from_db()
    assert service.subscriptions_api_key_hash != key
    assert service.subscriptions_api_key_hash == (
        models.Service.hash_subscriptions_api_key(key)
    )


def _admin_client():
    client = Client()
    client.force_login(factories.UserFactory(is_staff=True, is_superuser=True))
    return client


def _admin_key_url(service, action):
    return reverse(
        "admin:core_service_subscriptions_api_key", args=[service.pk, action]
    )


def test_admin_generate_subscriptions_api_key():
    """The admin generates a key, shown once in the success message."""
    service = factories.ServiceFactory()

    response = _admin_client().post(_admin_key_url(service, "generate"), follow=True)

    assert response.status_code == 200
    service.refresh_from_db()
    assert service.subscriptions_api_key_hash
    [message] = [str(m) for m in response.context["messages"]]
    key = message.rsplit(" ", 1)[-1]
    assert models.Service.hash_subscriptions_api_key(key) == (
        service.subscriptions_api_key_hash
    )
    assert _client(key).get(_list_url(service)).status_code == 200


def test_admin_regenerate_replaces_subscriptions_api_key(setup):
    """Generating again invalidates the previous key."""
    _admin_client().post(_admin_key_url(setup["service"], "generate"))

    assert setup["client"].get(_list_url(setup["service"])).status_code == 401


def test_admin_revoke_subscriptions_api_key(setup):
    """A revoked key is refused."""
    response = _admin_client().post(_admin_key_url(setup["service"], "revoke"))

    assert response.status_code == 302
    setup["service"].refresh_from_db()
    assert setup["service"].subscriptions_api_key_hash is None
    assert setup["client"].get(_list_url(setup["service"])).status_code == 401


def test_admin_subscriptions_api_key_requires_post(setup):
    """A GET changes nothing."""
    response = _admin_client().get(_admin_key_url(setup["service"], "revoke"))

    assert response.status_code == 404
    setup["service"].refresh_from_db()
    assert setup["service"].subscriptions_api_key_hash is not None


def test_admin_subscriptions_api_key_requires_staff(setup):
    """Non-staff users cannot generate a key."""
    client = Client()
    client.force_login(factories.UserFactory())

    client.post(_admin_key_url(setup["service"], "generate"))

    assert setup["client"].get(_list_url(setup["service"])).status_code == 200


def test_admin_duplicate_service_drops_subscriptions_api_key(setup):
    """A duplicated service starts without a key."""
    _admin_client().post(
        reverse("admin:core_service_changelist"),
        {"action": "duplicate_service", "_selected_action": [setup["service"].pk]},
    )

    copy = models.Service.objects.get(name=f"{setup['service'].name} (copy)")
    assert copy.subscriptions_api_key_hash is None


# --- Authentication ---


def test_missing_key_rejected(setup):
    """No Authorization header: 401."""
    response = APIClient().get(_list_url(setup["service"]))
    assert response.status_code == 401


def test_invalid_key_rejected(setup):
    """An unknown key: 401."""
    response = _client("wrong").get(_list_url(setup["service"]))
    assert response.status_code == 401


def test_empty_key_rejected():
    """An empty bearer token never authenticates."""
    service = factories.ServiceFactory()
    response = _client("").get(_list_url(service))
    assert response.status_code == 401


def test_other_service_keys_rejected(setup):
    """The service's other keys and operator keys are not accepted here."""
    service = setup["service"]
    service.external_management_api_key = "management-key"
    service.config = {**(service.config or {}), "entitlements_api_key": "ent-key"}
    service.save()
    setup["operator"].external_management_api_key = "operator-key"
    setup["operator"].save()

    for key in ("management-key", "ent-key", "operator-key"):
        assert _client(key).get(_list_url(service)).status_code == 401

    response = APIClient().get(
        _list_url(service), headers={"X-Service-Auth": "Bearer ent-key"}
    )
    assert response.status_code == 401


def test_session_user_rejected(setup):
    """Even a superuser session cannot use these endpoints."""
    client = APIClient()
    client.force_login(factories.UserFactory(is_staff=True, is_superuser=True))

    assert client.get(_list_url(setup["service"])).status_code == 401


def test_key_not_accepted_on_operator_subscription_api(setup):
    """The key does not open the operator subscription endpoint."""
    response = setup["client"].patch(
        f"/api/v1.0/operators/{setup['operator'].id}/organizations/"
        f"{setup['organization'].id}/services/{setup['service'].id}/subscription/",
        {"is_active": True},
        format="json",
    )
    assert response.status_code in (401, 403)
    assert not models.ServiceSubscription.objects.exists()


def test_key_not_accepted_on_entitlements_api(setup):
    """The key is not an entitlements key."""
    response = APIClient().get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": setup["service"].id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": setup["organization"].siret,
        },
        headers={"X-Service-Auth": f"Bearer {setup['key']}"},
    )
    assert response.status_code == 401


# --- Scoping to the key's service ---


def test_other_service_urls_forbidden(setup):
    """A key only works on the URLs of its own service."""
    other_service = factories.ServiceFactory()
    factories.OperatorServiceConfigFactory(
        operator=setup["operator"], service=other_service
    )
    other_subscription = factories.ServiceSubscriptionFactory(
        organization=setup["organization"],
        service=other_service,
        operator=setup["operator"],
    )
    client = setup["client"]

    assert client.get(_list_url(other_service)).status_code == 403
    assert (
        client.post(
            _list_url(other_service), _create_body(setup), format="json"
        ).status_code
        == 403
    )
    assert client.get(_operators_url(other_service)).status_code == 403
    detail = _detail_url(other_service, other_subscription)
    assert client.get(detail).status_code == 403
    assert client.patch(detail, {"is_active": False}, format="json").status_code == 403
    assert client.delete(detail).status_code == 403

    other_subscription.refresh_from_db()
    assert other_subscription.is_active is True
    assert (
        models.ServiceSubscription.objects.filter(service=setup["service"]).count() == 0
    )


def test_other_service_subscription_not_found_on_own_url(setup):
    """Another service's subscription id is not found under the key's service."""
    other_subscription = factories.ServiceSubscriptionFactory(
        organization=setup["organization"],
        operator=setup["operator"],
    )
    detail = _detail_url(setup["service"], other_subscription)
    client = setup["client"]

    assert client.get(detail).status_code == 404
    assert client.patch(detail, {"is_active": False}, format="json").status_code == 404
    assert client.delete(detail).status_code == 404
    other_subscription.refresh_from_db()
    assert other_subscription.is_active is True


def test_create_body_cannot_name_a_service(setup):
    """Only the key's service is ever used: a service in the body is refused."""
    other_service = factories.ServiceFactory()
    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, service=other_service.id),
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {"service": ["Unknown field."]}
    assert not models.ServiceSubscription.objects.exists()


# --- List and retrieve ---


def test_list_subscriptions(setup):
    """Lists the service's subscriptions only, with the exposed fields."""
    subscription = _subscribe(setup)
    factories.ServiceSubscriptionFactory(
        organization=setup["organization"], operator=setup["operator"]
    )

    response = setup["client"].get(_list_url(setup["service"]))

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    [item] = data["results"]
    assert item.pop("created_at")
    assert item.pop("updated_at")
    organization = setup["organization"]
    assert item == {
        "id": str(subscription.id),
        "organization": {
            "id": str(organization.id),
            "siret": organization.siret,
            "name": organization.name,
            "type": organization.type,
        },
        "operator": {
            "id": str(setup["operator"].id),
            "name": "Operator",
            "url": "https://op.fr",
        },
        "is_active": True,
        "metadata": {},
    }


def test_list_subscriptions_filters(setup):
    """Filters by siret, operator_id and is_active."""
    active = _subscribe(setup)
    other_organization = factories.OrganizationFactory()
    other_operator = factories.OperatorFactory()
    inactive = factories.ServiceSubscriptionFactory(
        organization=other_organization,
        service=setup["service"],
        operator=other_operator,
        is_active=False,
    )
    client = setup["client"]
    url = _list_url(setup["service"])

    def ids(params):
        response = client.get(url, params)
        assert response.status_code == 200
        return [item["id"] for item in response.json()["results"]]

    assert ids({"siret": setup["organization"].siret}) == [str(active.id)]
    assert ids({"operator_id": str(other_operator.id)}) == [str(inactive.id)]
    assert ids({"is_active": "false"}) == [str(inactive.id)]
    assert ids({"siret": "00000000000000"}) == []


def test_retrieve_subscription(setup):
    """Reads one of the service's subscriptions."""
    subscription = _subscribe(setup)

    response = setup["client"].get(_detail_url(setup["service"], subscription))

    assert response.status_code == 200
    assert response.json()["id"] == str(subscription.id)
    # The factory's metadata keys are not writable by the service: not exposed.
    assert subscription.metadata
    assert response.json()["metadata"] == {}


# --- Create ---


@pytest.mark.parametrize("is_active", [True, False])
def test_create_subscription(setup, is_active):
    """Creates a subscription with the requested is_active."""
    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, is_active=is_active),
        format="json",
    )

    assert response.status_code == 201
    subscription = models.ServiceSubscription.objects.get()
    assert subscription.service == setup["service"]
    assert subscription.organization == setup["organization"]
    assert subscription.operator == setup["operator"]
    assert subscription.is_active is is_active
    assert response.json()["id"] == str(subscription.id)
    assert response.json()["is_active"] is is_active


@pytest.mark.parametrize("missing", ["siret", "operator_id", "is_active"])
def test_create_subscription_requires_fields(setup, missing):
    """siret, operator_id and is_active are all required."""
    body = _create_body(setup)
    del body[missing]

    response = setup["client"].post(_list_url(setup["service"]), body, format="json")

    assert response.status_code == 400
    assert missing in response.json()
    assert not models.ServiceSubscription.objects.exists()


def test_create_subscription_rejects_unknown_fields(setup):
    """Fields the key cannot set are refused, not ignored."""
    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, entitlements=[]),
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {"entitlements": ["Unknown field."]}


def test_create_subscription_rejects_metadata_keys(setup):
    """Metadata keys not allowed for the service type are refused."""
    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, metadata={"epci_delegation": False}),
        format="json",
    )
    assert response.status_code == 400
    assert response.json() == {
        "metadata": ["Not writable with a subscriptions API key: epci_delegation."]
    }
    assert not models.ServiceSubscription.objects.exists()


def test_create_subscription_unknown_siret(setup):
    """An unknown SIRET is refused."""
    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, siret="00000000000000"),
        format="json",
    )
    assert response.status_code == 400
    assert "siret" in response.json()


def _assert_operator_refused(setup, operator):
    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, operator_id=str(operator.id)),
        format="json",
    )
    assert response.status_code == 400
    assert "operator_id" in response.json()
    assert not models.ServiceSubscription.objects.exists()


def test_create_subscription_operator_without_role(setup):
    """The operator must manage the organization."""
    operator = factories.OperatorFactory()
    factories.OperatorServiceConfigFactory(operator=operator, service=setup["service"])
    _assert_operator_refused(setup, operator)


def test_create_subscription_operator_not_configured_for_service(setup):
    """The operator must be configured for the service."""
    operator = factories.OperatorFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=setup["organization"]
    )
    _assert_operator_refused(setup, operator)


def test_create_subscription_inactive_operator(setup):
    """The operator must be active."""
    setup["operator"].is_active = False
    setup["operator"].save()
    _assert_operator_refused(setup, setup["operator"])


@pytest.mark.parametrize("same_operator", [True, False])
def test_create_subscription_already_subscribed(setup, same_operator):
    """An organization already subscribed to the service: 409, nothing changes."""
    operator = setup["operator"] if same_operator else factories.OperatorFactory()
    existing = factories.ServiceSubscriptionFactory(
        organization=setup["organization"],
        service=setup["service"],
        operator=operator,
        is_active=False,
    )

    response = setup["client"].post(
        _list_url(setup["service"]), _create_body(setup), format="json"
    )

    assert response.status_code == 409
    existing.refresh_from_db()
    assert existing.is_active is False
    assert existing.operator == operator


def test_create_active_subscription_checks_activation_rules(setup):
    """Activation rules apply: an active subscription needs the required services,
    an inactive one does not."""
    setup["service"].required_services.add(factories.ServiceFactory())

    response = setup["client"].post(
        _list_url(setup["service"]), _create_body(setup), format="json"
    )
    assert response.status_code == 400
    assert not models.ServiceSubscription.objects.exists()

    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, is_active=False),
        format="json",
    )
    assert response.status_code == 201


def test_create_subscription_applies_service_metadata_validation(setup):
    """Creation goes through the operator API's subscription validation, which
    normalizes the metadata of some service types (here "domains")."""
    setup["service"].type = "domains"
    setup["service"].save()

    response = setup["client"].post(
        _list_url(setup["service"]), _create_body(setup), format="json"
    )

    assert response.status_code == 201
    assert models.ServiceSubscription.objects.get().metadata == {
        "domains": [],
        "website": {},
    }


def test_create_proconnect_subscription_uses_organization_domain(setup):
    """The ProConnect validation resolves the domains from the organization."""
    setup["service"].type = "proconnect"
    setup["service"].config = {"idp_id": "idp"}
    setup["service"].save()
    # type "other" takes its mail domain from adresse_messagerie as is.
    setup["organization"].type = "other"
    setup["organization"].adresse_messagerie = "mairie@commune.fr"
    setup["organization"].save()
    assert setup["organization"].mail_domain == "commune.fr"

    response = setup["client"].post(
        _list_url(setup["service"]),
        _create_body(setup, is_active=False),
        format="json",
    )

    assert response.status_code == 201
    assert models.ServiceSubscription.objects.get().metadata == {
        "domains": ["commune.fr"]
    }


# --- Update and delete ---


@pytest.mark.parametrize("is_active", [True, False])
def test_update_is_active(setup, is_active):
    """PATCH sets is_active."""
    subscription = _subscribe(setup, is_active=not is_active)

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"is_active": is_active},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is is_active
    subscription.refresh_from_db()
    assert subscription.is_active is is_active


def test_update_requires_a_field(setup):
    """PATCH without is_active, operator_id nor metadata keys is refused."""
    subscription = _subscribe(setup)

    for body in ({}, {"metadata": {}}):
        response = setup["client"].patch(
            _detail_url(setup["service"], subscription), body, format="json"
        )

        assert response.status_code == 400
        assert "non_field_errors" in response.json()


def test_update_rejects_other_fields(setup):
    """Only is_active, the operator and allowed metadata keys can be changed."""
    subscription = _subscribe(setup)

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"is_active": False, "entitlements": []},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"entitlements": ["Unknown field."]}
    subscription.refresh_from_db()
    assert subscription.is_active is True


def test_update_rejects_metadata_keys(setup):
    """Metadata keys not allowed for the service type are refused."""
    subscription = _subscribe(setup)

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"is_active": False, "metadata": {"auto_admin": "all"}},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "metadata": ["Not writable with a subscriptions API key: auto_admin."]
    }
    subscription.refresh_from_db()
    assert subscription.is_active is True
    assert "auto_admin" not in subscription.metadata


# --- BAL: epci_delegation ---


@pytest.fixture
def bal_setup(setup):
    """The setup service as a BAL service."""
    setup["service"].type = "bal"
    setup["service"].save()
    return setup


@pytest.mark.parametrize("epci_delegation", [True, False])
def test_bal_create_with_epci_delegation(bal_setup, epci_delegation):
    """A BAL service can set epci_delegation on creation."""
    response = bal_setup["client"].post(
        _list_url(bal_setup["service"]),
        _create_body(bal_setup, metadata={"epci_delegation": epci_delegation}),
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["metadata"] == {"epci_delegation": epci_delegation}
    assert models.ServiceSubscription.objects.get().metadata == {
        "epci_delegation": epci_delegation
    }


def test_bal_epci_delegation_must_be_boolean(bal_setup):
    """The BAL validation of the operator API applies."""
    response = bal_setup["client"].post(
        _list_url(bal_setup["service"]),
        _create_body(bal_setup, metadata={"epci_delegation": "no"}),
        format="json",
    )

    assert response.status_code == 400
    assert not models.ServiceSubscription.objects.exists()


def test_bal_auto_admin_not_writable(bal_setup):
    """Only epci_delegation is allowed for BAL, not auto_admin."""
    response = bal_setup["client"].post(
        _list_url(bal_setup["service"]),
        _create_body(bal_setup, metadata={"auto_admin": "all"}),
        format="json",
    )

    assert response.status_code == 400
    assert "metadata" in response.json()


def test_bal_update_epci_delegation_keeps_other_metadata(bal_setup):
    """PATCH changes epci_delegation only, the other keys stay, and only the
    allowed keys are returned."""
    subscription = _subscribe(
        bal_setup, metadata={"auto_admin": "all", "notes": "kept"}
    )

    response = bal_setup["client"].patch(
        _detail_url(bal_setup["service"], subscription),
        {"metadata": {"epci_delegation": False}},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["metadata"] == {"epci_delegation": False}
    subscription.refresh_from_db()
    assert subscription.metadata == {
        "auto_admin": "all",
        "notes": "kept",
        "epci_delegation": False,
    }


def test_update_metadata_merges_without_type_validator(setup, monkeypatch):
    """For a service type whose validation does not merge metadata, the allowed
    keys are still merged into the stored metadata, not replacing it."""
    monkeypatch.setitem(
        service_subscriptions.SERVICE_KEY_METADATA_KEYS,
        setup["service"].type,
        {"allowed"},
    )
    subscription = _subscribe(setup, metadata={"other": "kept"})

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"metadata": {"allowed": 1}},
        format="json",
    )

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.metadata == {"other": "kept", "allowed": 1}


def _eligible_operator(setup, **osc_kwargs):
    operator = factories.OperatorFactory(name="New operator")
    factories.OperatorServiceConfigFactory(
        operator=operator, service=setup["service"], **osc_kwargs
    )
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=setup["organization"]
    )
    return operator


def test_update_operator(setup):
    """PATCH operator_id moves the subscription to another eligible operator."""
    subscription = _subscribe(setup)
    new_operator = _eligible_operator(setup)

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"operator_id": str(new_operator.id)},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["operator"]["id"] == str(new_operator.id)
    subscription.refresh_from_db()
    assert subscription.operator == new_operator
    assert subscription.is_active is True


def test_update_operator_and_is_active(setup):
    """Both fields can change in one PATCH."""
    subscription = _subscribe(setup, is_active=False)
    new_operator = _eligible_operator(setup)

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"operator_id": str(new_operator.id), "is_active": True},
        format="json",
    )

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.operator == new_operator
    assert subscription.is_active is True


def test_update_operator_not_eligible(setup):
    """The new operator must manage the organization and be configured for the
    service."""
    subscription = _subscribe(setup)
    configured_only = factories.OperatorFactory()
    factories.OperatorServiceConfigFactory(
        operator=configured_only, service=setup["service"]
    )

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"operator_id": str(configured_only.id), "is_active": False},
        format="json",
    )

    assert response.status_code == 400
    assert "operator_id" in response.json()
    subscription.refresh_from_db()
    assert subscription.operator == setup["operator"]
    assert subscription.is_active is True


def test_update_operator_checks_activation_rules(setup):
    """An active subscription cannot move to an operator whose config forbids
    activating it."""
    subscription = _subscribe(setup)
    new_operator = _eligible_operator(
        setup, config_override={"population_limits": {"commune": 10}}
    )

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"operator_id": str(new_operator.id)},
        format="json",
    )

    assert response.status_code == 400
    subscription.refresh_from_db()
    assert subscription.operator == setup["operator"]


def test_update_activation_checks_activation_rules(setup):
    """Activating still applies the activation rules."""
    subscription = _subscribe(setup, is_active=False)
    setup["service"].required_services.add(factories.ServiceFactory())

    response = setup["client"].patch(
        _detail_url(setup["service"], subscription),
        {"is_active": True},
        format="json",
    )

    assert response.status_code == 400
    subscription.refresh_from_db()
    assert subscription.is_active is False


def test_put_not_allowed(setup):
    """Only PATCH updates."""
    subscription = _subscribe(setup)
    response = setup["client"].put(
        _detail_url(setup["service"], subscription),
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 405


def test_delete_subscription(setup):
    """DELETE removes the subscription."""
    subscription = _subscribe(setup)

    response = setup["client"].delete(_detail_url(setup["service"], subscription))

    assert response.status_code == 204
    assert not models.ServiceSubscription.objects.filter(pk=subscription.pk).exists()


# --- Operators ---


def test_list_operators(setup):
    """Active operators configured for the service, with or without a role."""
    unmanaging = factories.OperatorFactory(name="Another")
    factories.OperatorServiceConfigFactory(
        operator=unmanaging, service=setup["service"]
    )
    inactive = factories.OperatorFactory(is_active=False)
    factories.OperatorServiceConfigFactory(operator=inactive, service=setup["service"])
    factories.OperatorServiceConfigFactory(service=factories.ServiceFactory())

    response = setup["client"].get(_operators_url(setup["service"]))

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"id": str(unmanaging.id), "name": "Another", "url": unmanaging.url},
        {"id": str(setup["operator"].id), "name": "Operator", "url": "https://op.fr"},
    ]


def test_list_operators_for_siret(setup):
    """With siret, only the operators managing that organization."""
    unmanaging = factories.OperatorFactory()
    factories.OperatorServiceConfigFactory(
        operator=unmanaging, service=setup["service"]
    )
    client = setup["client"]
    url = _operators_url(setup["service"])

    response = client.get(url, {"siret": setup["organization"].siret})
    assert [op["id"] for op in response.json()["results"]] == [
        str(setup["operator"].id)
    ]

    for siret in ("00000000000000", ""):
        response = client.get(url, {"siret": siret})
        assert response.status_code == 200
        assert response.json()["results"] == []
