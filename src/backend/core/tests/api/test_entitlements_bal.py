# pylint: disable=too-many-lines
"""
Test the BAL service: can_admin_communes entitlement, subscription metadata
and service-link scope validation.
"""

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.resolvers import get_admin_entitlement_resolver
from core.services.bal import CHANNELS

pytestmark = pytest.mark.django_db

# Above the default auto-admin population threshold, so that the population
# fallback does not grant anything unless a test asks for it.
LARGE_POPULATION = 50000


def _make_bal_service(**config):
    """Create a bal service with an auth key."""
    return factories.ServiceFactory(
        type="bal",
        config={"entitlements_api_key": "test_token", **config},
    )


def _make_org(operator, **kwargs):
    """Create an organization managed by the operator."""
    kwargs.setdefault("population", LARGE_POPULATION)
    organization = factories.OrganizationFactory(**kwargs)
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    return organization


def _subscribe(organization, service, operator, **kwargs):
    return factories.ServiceSubscriptionFactory(
        organization=organization, service=service, operator=operator, **kwargs
    )


def _make_account(organization, roles=None, external_id="xyz"):
    return factories.AccountFactory(
        organization=organization,
        type="user",
        external_id=external_id,
        email="test@example.com",
        roles=roles or [],
    )


def _can_admin_communes(service, siret, account_email=None, account_id=None):
    """Call the entitlements endpoint and return can_admin_communes."""
    params = {
        "service_id": service.id,
        "account_type": "user",
        "siret": siret,
    }
    if account_email:
        params["account_email"] = account_email
    if account_id:
        params["account_id"] = account_id
    response = APIClient().get(
        "/api/v1.0/entitlements/",
        query_params=params,
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    return response.json()["entitlements"]["can_admin_communes"]


# --- Commune ---


def test_bal_commune_org_admin_gets_all_channels():
    """Commune org-level admin gets all channels on that commune."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune, roles=["admin"])

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {
        commune.code_insee: CHANNELS
    }


def test_bal_commune_not_admin_gets_empty():
    """Commune user without any admin path gets an empty dict."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune)

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {}


def test_bal_commune_population_auto_admin():
    """Small commune (below threshold) auto-admins anyone querying it."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, population=1000)
    service = _make_bal_service()
    _subscribe(commune, service, operator)

    assert _can_admin_communes(
        service, commune.siret, account_email="anyone@example.com"
    ) == {commune.code_insee: CHANNELS}


def test_bal_commune_auto_admin_manual_excludes():
    """auto_admin='manual' disables the population fallback."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, population=1000)
    service = _make_bal_service()
    _subscribe(commune, service, operator, metadata={"auto_admin": "manual"})

    assert (
        _can_admin_communes(service, commune.siret, account_email="anyone@example.com")
        == {}
    )


def test_bal_commune_adresse_messagerie():
    """Email matching the commune's adresse_messagerie grants admin."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, adresse_messagerie="contact@mairie.fr")
    service = _make_bal_service()
    _subscribe(commune, service, operator)

    assert _can_admin_communes(
        service, commune.siret, account_email="CONTACT@mairie.fr"
    ) == {commune.code_insee: CHANNELS}


def test_bal_commune_auto_admin_all():
    """auto_admin='all' grants admin regardless of population."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator, metadata={"auto_admin": "all"})

    assert _can_admin_communes(
        service, commune.siret, account_email="anyone@example.com"
    ) == {commune.code_insee: CHANNELS}


def test_bal_commune_population_above_threshold_excluded():
    """A commune above the default population threshold gets no auto-admin."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, population=5000)
    service = _make_bal_service()
    _subscribe(commune, service, operator)

    assert (
        _can_admin_communes(service, commune.siret, account_email="anyone@example.com")
        == {}
    )


def test_bal_commune_custom_population_threshold():
    """service.config['auto_admin_population_threshold'] overrides the default."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, population=5000)
    service = _make_bal_service(auto_admin_population_threshold=10000)
    _subscribe(commune, service, operator)

    assert _can_admin_communes(
        service, commune.siret, account_email="anyone@example.com"
    ) == {commune.code_insee: CHANNELS}


def test_bal_commune_requires_active_subscription():
    """An inactive BAL subscription excludes the commune even for an admin."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, population=1000)
    service = _make_bal_service()
    _subscribe(commune, service, operator, is_active=False)
    _make_account(commune, roles=["admin"])

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {}


def test_bal_non_commune_non_epci_covers_nothing():
    """An admin of an organization that is neither a commune nor an EPCI gets nothing."""
    operator = factories.OperatorFactory()
    departement = _make_org(operator, type="departement")
    service = _make_bal_service()
    _subscribe(departement, service, operator)
    _make_account(departement, roles=["admin"])

    assert _can_admin_communes(service, departement.siret, account_id="xyz") == {}


# --- Scoped service-link admin ---


def test_bal_commune_scoped_service_admin():
    """Service-link admin with a channels scope gets only those channels."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["channel_formulaire", "channel_api_depot"]},
    )

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {
        commune.code_insee: ["channel_api_depot", "channel_formulaire"]
    }


def test_bal_commune_unrestricted_service_admin():
    """Service-link admin with an empty scope gets all channels."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune).service_links.create(service=service, role="admin", scope={})

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {
        commune.code_insee: CHANNELS
    }


def test_bal_scoped_admin_on_auto_admin_commune_gets_all_channels():
    """Auto-admin on the queried commune unions with a narrower scoped link."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator, population=1000)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["channel_api_depot"]},
    )

    assert _can_admin_communes(
        service, commune.siret, account_id="xyz", account_email="test@example.com"
    ) == {commune.code_insee: CHANNELS}


@pytest.mark.parametrize(
    "scope",
    [
        ["channel_api_depot"],
        {"channels": []},
        {"channels": "channel_api_depot"},
        {"channels": ["bogus_channel"]},
        {"channels": [{"not": "hashable"}]},
        {"communes": {"12345": []}},
    ],
)
def test_bal_malformed_scope_grants_nothing(scope):
    """A malformed or empty-channels stored scope grants nothing, never all."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune).service_links.create(
        service=service, role="admin", scope=scope
    )

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {}


def test_bal_scope_unknown_channels_are_dropped():
    """Unknown channel names in a scope are ignored, known ones kept."""
    operator = factories.OperatorFactory()
    commune = _make_org(operator)
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    _make_account(commune).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["bogus", "channel_formulaire"]},
    )

    assert _can_admin_communes(service, commune.siret, account_id="xyz") == {
        commune.code_insee: ["channel_formulaire"]
    }


# --- EPCI ---


def test_bal_epci_org_admin_gets_delegated_member_communes():
    """EPCI org-level admin gets all its delegated member communes."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member1 = factories.OrganizationFactory(epci_siren=epci.siren)
    member2 = factories.OrganizationFactory(epci_siren=epci.siren)
    outsider = factories.OrganizationFactory(epci_siren="111111111")

    service = _make_bal_service()
    for organization in (epci, member1, member2, outsider):
        _subscribe(organization, service, operator)
    _make_account(epci, roles=["admin"])

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {
        member1.code_insee: CHANNELS,
        member2.code_insee: CHANNELS,
    }


def test_bal_epci_member_without_active_subscription_excluded():
    """A delegated commune without an active BAL subscription is excluded."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member_active = factories.OrganizationFactory(epci_siren=epci.siren)
    member_inactive = factories.OrganizationFactory(epci_siren=epci.siren)

    service = _make_bal_service()
    _subscribe(epci, service, operator)
    _subscribe(member_active, service, operator)
    _subscribe(member_inactive, service, operator, is_active=False)
    _make_account(epci, roles=["admin"])

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {
        member_active.code_insee: CHANNELS
    }


def test_bal_epci_member_opted_out_excluded():
    """A commune with epci_delegation=false is excluded from EPCI admin."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member_delegated = factories.OrganizationFactory(epci_siren=epci.siren)
    member_opted_out = factories.OrganizationFactory(epci_siren=epci.siren)

    service = _make_bal_service()
    _subscribe(epci, service, operator)
    _subscribe(member_delegated, service, operator)
    _subscribe(member_opted_out, service, operator, metadata={"epci_delegation": False})
    _make_account(epci, roles=["admin"])

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {
        member_delegated.code_insee: CHANNELS
    }


def test_bal_epci_requires_explicit_admin():
    """An EPCI gets no auto-admin path, even with small member communes."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999", population=1000)
    member = factories.OrganizationFactory(epci_siren=epci.siren, population=1000)

    service = _make_bal_service()
    _subscribe(epci, service, operator)
    _subscribe(member, service, operator)

    assert (
        _can_admin_communes(service, epci.siret, account_email="anyone@example.com")
        == {}
    )


def test_bal_epci_adresse_messagerie_does_not_grant():
    """adresse_messagerie matching does not grant EPCI access (explicit roles only)."""
    operator = factories.OperatorFactory()
    epci = _make_org(
        operator,
        type="epci",
        siren="999999999",
        adresse_messagerie="contact@epci.fr",
    )
    member = factories.OrganizationFactory(epci_siren=epci.siren)

    service = _make_bal_service()
    _subscribe(epci, service, operator)
    _subscribe(member, service, operator)

    assert (
        _can_admin_communes(service, epci.siret, account_email="contact@epci.fr") == {}
    )


def test_bal_epci_scoped_service_admin_applies_to_all_members():
    """EPCI service-link channels apply to every delegated member commune."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member1 = factories.OrganizationFactory(epci_siren=epci.siren)
    member2 = factories.OrganizationFactory(epci_siren=epci.siren)

    service = _make_bal_service()
    for organization in (epci, member1, member2):
        _subscribe(organization, service, operator)
    _make_account(epci).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["channel_api_depot"]},
    )

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {
        member1.code_insee: ["channel_api_depot"],
        member2.code_insee: ["channel_api_depot"],
    }


def test_bal_epci_without_own_subscription_excludes_members():
    """EPCI delegation requires the EPCI's own active BAL subscription."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member1 = factories.OrganizationFactory(epci_siren=epci.siren)
    member2 = factories.OrganizationFactory(epci_siren=epci.siren)

    service = _make_bal_service()
    _subscribe(member1, service, operator)
    _subscribe(member2, service, operator)
    _make_account(epci, roles=["admin"])

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {}


def test_bal_epci_own_subscription_inactive_excludes_members():
    """An inactive EPCI BAL subscription disables delegation to its members."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member = factories.OrganizationFactory(epci_siren=epci.siren)

    service = _make_bal_service()
    _subscribe(epci, service, operator, is_active=False)
    _subscribe(member, service, operator)
    _make_account(epci, roles=["admin"])

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {}


def test_bal_epci_without_siren_covers_nothing():
    """An EPCI without a SIREN does not cover communes that have no EPCI."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren=None)
    orphan_commune = factories.OrganizationFactory(epci_siren=None)

    service = _make_bal_service()
    _subscribe(epci, service, operator)
    _subscribe(orphan_commune, service, operator)
    _make_account(epci, roles=["admin"])

    assert _can_admin_communes(service, epci.siret, account_id="xyz") == {}


# --- Cross-org ---


def test_bal_cross_org_manual_admin_when_queried_org_inactive():
    """An admin in one org still gets it when the queried org has no BAL sub."""
    operator = factories.OperatorFactory()
    queried_org = factories.OrganizationFactory(population=LARGE_POPULATION)
    managed_org = _make_org(operator)

    service = _make_bal_service()
    _subscribe(managed_org, service, operator)
    _make_account(managed_org, roles=["admin"])

    response = APIClient().get(
        "/api/v1.0/entitlements/",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "siret": queried_org.siret,
            "account_id": "xyz",
        },
        headers={"X-Service-Auth": "Bearer test_token"},
    )
    assert response.status_code == 200
    entitlements = response.json()["entitlements"]
    assert entitlements["can_access"] is False
    assert entitlements["can_admin_communes"] == {managed_org.code_insee: CHANNELS}


def test_bal_cross_org_unknown_siret():
    """Cross-org access is resolved even when the queried SIRET is unknown."""
    operator = factories.OperatorFactory()
    managed_org = _make_org(operator)

    service = _make_bal_service()
    _subscribe(managed_org, service, operator)
    _make_account(managed_org, roles=["admin"])

    assert _can_admin_communes(service, "99999999999999", account_id="xyz") == {
        managed_org.code_insee: CHANNELS
    }


def test_bal_cross_org_merges_multiple_orgs():
    """Adminships across orgs are merged into one dict."""
    operator = factories.OperatorFactory()
    org_a = _make_org(operator)
    org_b = _make_org(operator)

    service = _make_bal_service()
    _subscribe(org_a, service, operator)
    _subscribe(org_b, service, operator)
    _make_account(org_a, roles=["admin"])
    _make_account(org_b, roles=["admin"])

    assert _can_admin_communes(service, org_a.siret, account_id="xyz") == {
        org_a.code_insee: CHANNELS,
        org_b.code_insee: CHANNELS,
    }


def test_bal_cross_org_scoped_service_admin():
    """A scoped service-link admin in another org is honored cross-org."""
    operator = factories.OperatorFactory()
    queried_org = factories.OrganizationFactory(population=LARGE_POPULATION)
    managed_org = _make_org(operator)

    service = _make_bal_service()
    _subscribe(managed_org, service, operator)
    _make_account(managed_org).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["channel_moissonneur"]},
    )

    assert _can_admin_communes(service, queried_org.siret, account_id="xyz") == {
        managed_org.code_insee: ["channel_moissonneur"]
    }


def test_bal_channels_union_across_sources():
    """Channel sets from different sources covering the same commune are unioned."""
    operator = factories.OperatorFactory()
    epci = _make_org(operator, type="epci", siren="999999999")
    member = _make_org(operator, epci_siren=epci.siren)

    service = _make_bal_service()
    _subscribe(epci, service, operator)
    _subscribe(member, service, operator)

    # The same person has a scoped link on the EPCI and another scoped link on
    # the member commune: the channel sets must union.
    _make_account(epci).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["channel_moissonneur"]},
    )
    _make_account(member).service_links.create(
        service=service,
        role="admin",
        scope={"channels": ["channel_api_depot"]},
    )

    assert _can_admin_communes(
        service, member.siret, account_email="test@example.com"
    ) == {member.code_insee: ["channel_api_depot", "channel_moissonneur"]}


def test_bal_commune_auto_admin_does_not_apply_to_other_org():
    """Auto-admin paths only apply to the queried commune, not to other orgs."""
    operator = factories.OperatorFactory()
    queried_org = _make_org(operator, population=1000)
    other_org = _make_org(operator, population=1000)

    service = _make_bal_service()
    _subscribe(queried_org, service, operator)
    _subscribe(other_org, service, operator)

    assert _can_admin_communes(
        service, queried_org.siret, account_email="anyone@example.com"
    ) == {queried_org.code_insee: CHANNELS}


# --- Operator passthrough ---


def _operator_admin_setup(passthrough):
    user = factories.UserFactory(email="admin@operator.fr")
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    commune = factories.OrganizationFactory(population=LARGE_POPULATION)
    factories.OperatorOrganizationRoleFactory(
        operator=operator,
        organization=commune,
        operator_admins_have_admin_role=passthrough,
    )
    service = _make_bal_service()
    _subscribe(commune, service, operator)
    return service, commune


def test_bal_operator_admin_passthrough():
    """Operator admin with the flag gets covered communes of the managed org."""
    service, commune = _operator_admin_setup(passthrough=True)

    assert _can_admin_communes(
        service, commune.siret, account_email="admin@operator.fr"
    ) == {commune.code_insee: CHANNELS}


def test_bal_operator_admin_passthrough_flag_off():
    """Operator admin with the flag off gets nothing."""
    service, commune = _operator_admin_setup(passthrough=False)

    assert (
        _can_admin_communes(service, commune.siret, account_email="admin@operator.fr")
        == {}
    )


def test_bal_resolver_runs_without_active_subscription():
    """The BAL admin resolver is flagged to run without an active subscription."""
    bal_service = factories.ServiceFactory(type="bal")
    assert (
        get_admin_entitlement_resolver(bal_service).runs_without_active_subscription
        is True
    )


# --- Subscription metadata ---


def _subscription_client_setup(**subscription_kwargs):
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    commune = _make_org(operator)
    service = _make_bal_service()
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    _subscribe(commune, service, operator, **subscription_kwargs)
    url = (
        f"/api/v1.0/operators/{operator.id}/organizations/{commune.id}/"
        f"services/{service.id}/subscription/"
    )
    return client, url


def test_bal_subscription_patch_metadata_merges():
    """epci_delegation and auto_admin are merged into existing metadata."""
    client, url = _subscription_client_setup(metadata={"existing_key": "keep_me"})

    response = client.patch(
        url,
        {"metadata": {"epci_delegation": False, "auto_admin": "manual"}},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "existing_key": "keep_me",
        "epci_delegation": False,
        "auto_admin": "manual",
    }

    response = client.patch(url, {"metadata": {"epci_delegation": True}}, format="json")
    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "existing_key": "keep_me",
        "epci_delegation": True,
        "auto_admin": "manual",
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {"epci_delegation": "false"},
        {"epci_delegation": None},
        {"auto_admin": "invalid_value"},
        {"auto_admin": "all", "epci_delegation": 0},
    ],
)
def test_bal_subscription_patch_metadata_invalid(metadata):
    """Invalid epci_delegation or auto_admin values are rejected."""
    client, url = _subscription_client_setup()

    response = client.patch(url, {"metadata": metadata}, format="json")
    assert response.status_code == 400


# --- Service-link scope validation ---


def _service_link_client_setup():
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator = factories.OperatorFactory()
    factories.UserOperatorRoleFactory(user=user, operator=operator)
    commune = _make_org(operator)
    account = _make_account(commune)
    return client, account


@pytest.mark.parametrize(
    "scope",
    [{}, {"channels": ["channel_api_depot", "channel_mesadresses"]}],
)
def test_bal_service_link_valid_scope(scope):
    """An empty or channels BAL scope is stored."""
    client, account = _service_link_client_setup()
    service = _make_bal_service()

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/services/{service.id}/",
        {"roles": {"admin": {"scope": scope}}},
        format="json",
    )
    assert response.status_code == 200
    assert account.service_links.get(service=service).scope == scope


@pytest.mark.parametrize(
    "scope",
    [
        ["not", "an", "object"],
        None,
        {"channels": []},
        {"channels": "channel_api_depot"},
        {"channels": ["bogus_channel"]},
        {"channels": ["channel_api_depot"], "communes": {}},
        {"communes": {"12345": []}},
    ],
)
def test_bal_service_link_malformed_scope_rejected(scope):
    """A malformed BAL scope is rejected and nothing is stored."""
    client, account = _service_link_client_setup()
    service = _make_bal_service()

    response = client.patch(
        f"/api/v1.0/accounts/{account.id}/services/{service.id}/",
        {"roles": {"admin": {"scope": scope}}},
        format="json",
    )
    assert response.status_code == 400
    assert not account.service_links.exists()
