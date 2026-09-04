"""Tests for the domains service: subscription metadata and the external export."""

from django.conf import settings
from django.test import override_settings

import pytest
from rest_framework.test import APIClient

from core import factories
from core.services import dns as dns_service
from core.services import domains as domains_service

pytestmark = pytest.mark.django_db

DOMAINS_API_KEY = "test-domains-secret"
EXPORT_ENDPOINT = "/api/v1.0/domains/"


def _setup(user=None):
    """Create an operator/organization/domains-service triple wired together."""
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(type="domains")
    factories.OperatorServiceConfigFactory(operator=operator, service=service)
    if user:
        factories.UserOperatorRoleFactory(user=user, operator=operator)
    return operator, organization, service


def _subscription_url(operator, organization, service):
    return (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/services/{service.id}/subscription/"
    )


def test_domains_subscription_declare_domains():
    """Any operator member can declare domains; parking is the default website."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["Exemple.FR", "autre.fr"],
                "website": {"autre.fr": {"mode": "dns_a", "target": "192.0.2.1"}},
            }
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"] == {
        "domains": ["autre.fr", "exemple.fr"],
        "website": {
            "autre.fr": {"mode": "dns_a", "target": "192.0.2.1"},
            "exemple.fr": {"mode": "parking"},
        },
    }


def test_domains_subscription_cname_target_normalized():
    """A CNAME target is lowercased and loses its trailing dot."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["exemple.fr"],
                "website": {
                    "exemple.fr": {"mode": "dns_cname", "target": "Cible.Exemple.FR."}
                },
            }
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["website"] == {
        "exemple.fr": {"mode": "dns_cname", "target": "cible.exemple.fr"}
    }


@pytest.mark.parametrize(
    "website",
    [
        {"exemple.fr": {"mode": "dns_a"}},
        {"exemple.fr": {"mode": "dns_a", "target": "pas-une-ip"}},
        {"exemple.fr": {"mode": "dns_a", "target": "cible.exemple.fr"}},
        # One bad address in the list fails the whole field.
        {"exemple.fr": {"mode": "dns_a", "target": "192.0.2.1, pas-une-ip"}},
        {"exemple.fr": {"mode": "dns_a", "target": "192.0.2.1/24"}},
        # A scoped address parses but means nothing in a zone.
        {"exemple.fr": {"mode": "dns_a", "target": "fe80::1%eth0"}},
        {"exemple.fr": {"mode": "dns_a", "target": ", ,"}},
        {
            "exemple.fr": {
                "mode": "dns_a",
                "target": ", ".join(f"192.0.2.{i}" for i in range(11)),
            }
        },
        {"exemple.fr": {"mode": "dns_cname", "target": "192.0.2.1"}},
        {"exemple.fr": {"mode": "dns_cname", "target": ""}},
        {"exemple.fr": {"mode": "unknown"}},
        {"exemple.fr": "parking"},
        {"autre.fr": {"mode": "parking"}},
    ],
)
def test_domains_subscription_rejects_bad_website(website):
    """An unusable website configuration is refused instead of silently reset."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.fr"], "website": website}},
        format="json",
    )
    assert response.status_code == 400


def test_domains_subscription_preserves_other_metadata():
    """Keys we don't own are kept when domains are updated."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={"notes": "keep me", "domains": ["exemple.fr"]},
    )

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.fr", "autre.fr"]}},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "notes": "keep me",
        "domains": ["autre.fr", "exemple.fr"],
        "website": {
            "autre.fr": {"mode": "parking"},
            "exemple.fr": {"mode": "parking"},
        },
    }


def test_domains_subscription_rejects_invalid_domain():
    """A malformed domain is refused instead of being silently dropped."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["not a domain"]}},
        format="json",
    )
    assert response.status_code == 400
    assert "not a domain" in str(response.json())


def test_domains_subscription_rejects_website_for_undeclared_domain():
    """A website can only be configured for a declared domain."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["exemple.fr"],
                "website": {"autre.fr": {"mode": "parking"}},
            }
        },
        format="json",
    )
    assert response.status_code == 400
    assert "autre.fr" in str(response.json())


def test_domains_subscription_rejects_too_many_domains():
    """The bucket is capped."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": [f"domaine{i}.fr" for i in range(101)]}},
        format="json",
    )
    assert response.status_code == 400


def test_domains_subscription_rejects_domain_claimed_elsewhere():
    """A domain declared by another active subscription cannot be claimed again."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    other_organization = factories.OrganizationFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=other_organization
    )
    factories.ServiceSubscriptionFactory(
        organization=other_organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={"domains": ["exemple.fr"]},
    )

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.fr"]}, "is_active": True},
        format="json",
    )
    assert response.status_code == 400
    assert "exemple.fr" in str(response.json())


def test_domains_subscription_ignores_inactive_claim():
    """An inactive subscription does not reserve its domains."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    other_organization = factories.OrganizationFactory()
    factories.ServiceSubscriptionFactory(
        organization=other_organization,
        service=service,
        operator=operator,
        is_active=False,
        metadata={"domains": ["exemple.fr"]},
    )

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.fr"]}, "is_active": True},
        format="json",
    )
    assert response.status_code == 201


def test_domains_subscription_drops_website_when_domain_removed():
    """Removing a domain also drops its website configuration."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        metadata={
            "domains": ["exemple.fr"],
            "website": {"exemple.fr": {"mode": "dns_a", "target": "192.0.2.1"}},
        },
    )

    # The domain list changes without the caller sending a website config.
    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["autre.fr"]}},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "domains": ["autre.fr"],
        "website": {"autre.fr": {"mode": "parking"}},
    }


def _export(client, params=None, key=DOMAINS_API_KEY):
    headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
    return client.get(EXPORT_ENDPOINT, query_params=params or {}, headers=headers)


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_lists_all_domains():
    """Every domain of an active subscription is exported, with its website config."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={
            "domains": ["autre.fr", "exemple.fr"],
            "website": {"autre.fr": {"mode": "dns_a", "target": "192.0.2.1"}},
        },
    )

    response = _export(APIClient())
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    # An external server is not something we serve: it comes out as records, and the
    # mode says we serve nothing.
    assert [(r["domain"], r["website"], r["records"]) for r in data["results"]] == [
        (
            "autre.fr",
            {"mode": "none"},
            [{"prefix": "", "type": "A", "value": "192.0.2.1"}],
        ),
        ("exemple.fr", {"mode": "parking"}, []),
    ]
    entry = data["results"][0]
    assert entry["organization"]["siret"] == organization.siret
    assert entry["organization"]["name"] == organization.name
    assert entry["operator"]["name"] == operator.name


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
@pytest.mark.parametrize(
    "entry,records",
    [
        (
            {"mode": "dns_a", "target": "192.0.2.1, 2001:db8::1"},
            [
                {"prefix": "", "type": "A", "value": "192.0.2.1"},
                {"prefix": "", "type": "AAAA", "value": "2001:db8::1"},
            ],
        ),
        (
            {"mode": "dns_cname", "target": "cible.exemple.fr"},
            [{"prefix": "", "type": "CNAME", "value": "cible.exemple.fr"}],
        ),
        ({"mode": "parking"}, []),
        ({"mode": "redirect_301", "target": "https://exemple.fr"}, []),
    ],
)
def test_domains_export_records(entry, records):
    """The DNS modes are exported as records; the record type follows the family."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={"domains": ["exemple.fr"], "website": {"exemple.fr": entry}},
    )

    response = _export(APIClient())
    assert response.status_code == 200
    assert response.json()["results"][0]["records"] == records


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_keeps_redirect_target():
    """A redirection is something we serve, so it keeps its mode and its url."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={
            "domains": ["exemple.fr"],
            "website": {
                "exemple.fr": {"mode": "redirect_302", "target": "https://exemple.fr"}
            },
        },
    )

    response = _export(APIClient())
    assert response.json()["results"][0]["website"] == {
        "mode": "redirect_302",
        "target": "https://exemple.fr",
    }


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_is_unfiltered():
    """Every domain comes back, whatever serves it — the caller filters."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={
            "domains": ["autre.fr", "exemple.fr"],
            "website": {"autre.fr": {"mode": "dns_cname", "target": "cible.fr"}},
        },
    )

    response = _export(APIClient())
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert [r["domain"] for r in data["results"]] == ["autre.fr", "exemple.fr"]

    # A query string we no longer read changes nothing.
    assert _export(APIClient(), {"mode": "parking"}).json() == data


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_excludes_inactive_subscriptions():
    """A deactivated domains subscription exports nothing."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=False,
        metadata={"domains": ["exemple.fr"]},
    )

    response = _export(APIClient())
    assert response.status_code == 200
    assert response.json() == {"count": 0, "results": []}


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_excludes_other_service_types():
    """Domains stored by other services (e.g. ProConnect routing) are not exported."""
    operator = factories.OperatorFactory()
    organization = factories.OrganizationFactory()
    proconnect = factories.ServiceFactory(
        type="proconnect", config={"idp_id": "an-idp"}
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=proconnect,
        operator=operator,
        is_active=True,
        metadata={"domains": ["exemple.fr"]},
    )

    response = _export(APIClient())
    assert response.status_code == 200
    assert response.json() == {"count": 0, "results": []}


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_ignores_stale_and_broken_website_entries():
    """A config for an undeclared domain is dropped; an unusable one falls back to parking."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={
            "domains": ["autre.fr"],
            "website": {
                "exemple.fr": {"mode": "parking"},
                "autre.fr": {"mode": "dns_a"},
            },
        },
    )

    response = _export(APIClient())
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["domain"] == "autre.fr"
    assert data["results"][0]["website"] == {"mode": "parking"}


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
def test_domains_export_requires_key():
    """No or wrong key → 403."""
    client = APIClient()
    assert _export(client, key=None).status_code == 403
    assert _export(client, key="wrong-key").status_code == 403


@override_settings(DOMAINS_API_KEY=None)
def test_domains_export_closed_when_unconfigured():
    """When DOMAINS_API_KEY is unset the route is closed."""
    assert _export(APIClient()).status_code == 403


# --- Redirections, RPNT 1.2 and the DNS check ------------------------------


def _check_url(operator, organization):
    return (
        f"/api/v1.0/operators/{operator.id}/organizations/{organization.id}"
        f"/domains-check/"
    )


@pytest.mark.parametrize(
    "target,stored",
    [
        ("192.0.2.1", "192.0.2.1"),
        # IPv4 and IPv6 share the field; the record type follows from the family.
        ("192.0.2.1,2001:db8::1", "192.0.2.1, 2001:db8::1"),
        # Whitespace around the commas is the way people paste a list.
        ("  192.0.2.1 ,   2001:db8::1  ", "192.0.2.1, 2001:db8::1"),
        # An IPv6 address is stored compressed and lowercased.
        ("2001:0DB8:0000::0001", "2001:db8::1"),
        # Duplicates collapse, order is kept.
        ("198.51.100.7, 192.0.2.1, 198.51.100.7", "198.51.100.7, 192.0.2.1"),
    ],
)
def test_domains_subscription_addresses_normalized(target, stored):
    """The address field takes a comma-separated IPv4/IPv6 list."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["exemple.fr"],
                "website": {"exemple.fr": {"mode": "dns_a", "target": target}},
            }
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["website"] == {
        "exemple.fr": {"mode": "dns_a", "target": stored}
    }


@pytest.mark.parametrize(
    "target,stored",
    [
        ("https://exemple.fr/page", "https://exemple.fr/page"),
        # http is upgraded: we control the redirection we serve.
        ("http://exemple.fr/page", "https://exemple.fr/page"),
        # A bare host is read as a url, not as a path.
        ("exemple.fr/Page?a=1", "https://exemple.fr/Page?a=1"),
        ("https://Exemple.FR", "https://exemple.fr"),
    ],
)
def test_domains_subscription_redirect_target_normalized(target, stored):
    """A redirection target is normalized to an https url."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["exemple.fr"],
                "website": {"exemple.fr": {"mode": "redirect_301", "target": target}},
            }
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["website"] == {
        "exemple.fr": {"mode": "redirect_301", "target": stored}
    }


@pytest.mark.parametrize(
    "target",
    [
        "",
        "pas une url",
        "ftp://exemple.fr",
        "javascript:alert(1)",
        # A "user@host" url displays as one host and resolves as another.
        "https://exemple.fr@evil.example/",
        "https://192.0.2.1/",
        "https://localhost/",
    ],
)
def test_domains_subscription_rejects_bad_redirect(target):
    """A redirection needs a plain https url."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["exemple.fr"],
                "website": {"exemple.fr": {"mode": "redirect_302", "target": target}},
            }
        },
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "entry",
    [
        {"mode": "parking"},
        {"mode": "dns_a", "target": "192.0.2.1"},
        {"mode": "dns_cname", "target": "cible.exemple.fr"},
    ],
)
def test_domains_subscription_refuses_hosting_on_non_rpnt_domain(entry):
    """Serving a website — ours or theirs — needs an RPNT 1.2 conformant extension."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.com"], "website": {"exemple.com": entry}}},
        format="json",
    )
    assert response.status_code == 400
    assert "exemple.com" in str(response.json())


@pytest.mark.parametrize("mode", ["redirect_301", "redirect_302", "none"])
def test_domains_subscription_allows_redirects_on_non_rpnt_domain(mode):
    """A non-conformant domain can still redirect to the official one, or serve nothing."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    entry = {"mode": mode}
    if mode != "none":
        entry["target"] = "https://exemple.fr"

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.com"], "website": {"exemple.com": entry}}},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["website"]["exemple.com"]["mode"] == mode


def test_domains_subscription_non_rpnt_domain_defaults_to_none():
    """A domain we cannot park defaults to serving nothing, not to a parking page."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {"metadata": {"domains": ["exemple.com", "exemple.bzh"]}},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["metadata"]["website"] == {
        "exemple.bzh": {"mode": "parking"},
        "exemple.com": {"mode": "none"},
    }


@override_settings(DOMAINS_API_KEY=DOMAINS_API_KEY)
@pytest.mark.parametrize(
    "entry",
    [
        {"mode": "parking"},
        {"mode": "dns_a", "target": "192.0.2.1"},
    ],
)
def test_domains_export_ignores_hosting_stored_on_non_rpnt_domain(entry):
    """A website stored before the extension rule is not exported as one."""
    operator, organization, service = _setup()
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=True,
        metadata={"domains": ["exemple.com"], "website": {"exemple.com": entry}},
    )

    response = _export(APIClient())
    assert response.status_code == 200
    assert response.json()["results"][0]["website"] == {"mode": "none"}


def test_domains_check_reports_delegation_and_rpnt(monkeypatch):
    """The check returns the nameservers verdict and the RPNT 1.2 one per domain."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, _service = _setup(user)

    monkeypatch.setattr(
        dns_service,
        "nameservers_batch",
        lambda domains: {
            "exemple.fr": (["ns1.lst-domaines.fr", "ns2.lst-domaines.fr"], None),
            "exemple.com": (["ns1.autre.fr"], None),
            "inconnu.fr": ([], dns_service.ERROR_NXDOMAIN),
        },
    )

    response = client.post(
        _check_url(operator, organization),
        {"domains": ["Exemple.FR", "exemple.com", "inconnu.fr"]},
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["expected_nameservers"] == [
        "ns1.lst-domaines.fr",
        "ns2.lst-domaines.fr",
    ]
    assert {
        r["domain"]: (r["nameservers_valid"], r["rpnt_1_2_valid"], r["error"])
        for r in data["results"]
    } == {
        "exemple.fr": (True, True, None),
        "exemple.com": (False, False, None),
        "inconnu.fr": (False, True, "nxdomain"),
    }


def test_domains_check_ignores_malformed_domains(monkeypatch):
    """A half-typed domain is dropped, not a 400: the modal checks what is typed."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, _service = _setup(user)

    called = {}

    def _batch(domains):
        called["domains"] = domains
        return {domain: ([], dns_service.ERROR_NXDOMAIN) for domain in domains}

    monkeypatch.setattr(dns_service, "nameservers_batch", _batch)

    response = client.post(
        _check_url(operator, organization),
        {"domains": ["exemple.fr", "pas un domaine", ""]},
        format="json",
    )
    assert response.status_code == 200
    assert called["domains"] == ["exemple.fr"]
    assert [r["domain"] for r in response.json()["results"]] == ["exemple.fr"]


def test_domains_check_requires_operator_access():
    """A user without a role in the operator gets no check."""
    client = APIClient()
    client.force_login(factories.UserFactory())
    operator, organization, _service = _setup()

    response = client.post(
        _check_url(operator, organization), {"domains": ["exemple.fr"]}, format="json"
    )
    assert response.status_code == 403


# --- internationalized domains -----------------------------------------------


@pytest.mark.parametrize(
    "domain",
    [
        # The punycode form DILA publishes...
        "xn--stmearddeguron-rjb.fr",
        # ...and the unicode name it encodes.
        "stmearddegurçon.fr",
        # An IDN label anywhere in the name disqualifies it.
        "mairie.xn--stmearddeguron-rjb.fr",
    ],
)
def test_internationalized_domain_is_not_rpnt_1_2_valid(domain):
    """RPNT 1.2 refuses an IDN even on a sovereign extension."""
    assert domains_service.is_internationalized(domain) is True
    assert domains_service.is_rpnt_1_2_valid(domain) is False
    assert domains_service.default_mode(domain) == domains_service.MODE_NONE


def test_ascii_domain_is_not_flagged_as_internationalized():
    """Only the "xn--" prefix marks an A-label; "xn" alone is an ordinary word."""
    assert domains_service.is_internationalized("exemple.fr") is False
    assert domains_service.is_rpnt_1_2_valid("exemple.fr") is True
    # "xn" on its own is a perfectly ordinary label.
    assert domains_service.is_internationalized("xn.fr") is False
    assert domains_service.is_rpnt_1_2_valid("xn.fr") is True


def test_domains_subscription_refuses_parking_on_idn_domain():
    """A parking page needs an RPNT 1.2 domain, which an IDN never is."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, service = _setup(user)

    response = client.patch(
        _subscription_url(operator, organization, service),
        {
            "metadata": {
                "domains": ["xn--stmearddeguron-rjb.fr"],
                "website": {"xn--stmearddeguron-rjb.fr": {"mode": "parking"}},
            }
        },
        format="json",
    )
    assert response.status_code == 400


def test_domains_check_reports_idn_as_non_conformant(monkeypatch):
    """The check endpoint agrees: an IDN on a .fr is not RPNT 1.2 valid."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, _service = _setup(user)

    monkeypatch.setattr(
        dns_service,
        "nameservers_batch",
        lambda domains: {d: ([], dns_service.ERROR_NXDOMAIN) for d in domains},
    )

    response = client.post(
        _check_url(operator, organization),
        {"domains": ["xn--stmearddeguron-rjb.fr", "exemple.fr"]},
        format="json",
    )
    assert response.status_code == 200
    verdicts = {r["domain"]: r["rpnt_1_2_valid"] for r in response.json()["results"]}
    assert verdicts == {"xn--stmearddeguron-rjb.fr": False, "exemple.fr": True}


def test_domains_check_returns_the_modes_the_ui_needs(monkeypatch):
    """The check carries the mode rules, so the frontend never restates them."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    operator, organization, _service = _setup(user)

    monkeypatch.setattr(
        dns_service,
        "nameservers_batch",
        lambda domains: {d: ([], dns_service.ERROR_NXDOMAIN) for d in domains},
    )

    response = client.post(
        _check_url(operator, organization),
        {"domains": ["exemple.fr", "exemple.com"]},
        format="json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["modes_with_target"] == list(domains_service.MODES_WITH_TARGET)

    by_domain = {r["domain"]: r for r in data["results"]}
    # A conformant extension may use every mode, and parks by default.
    assert by_domain["exemple.fr"]["allowed_modes"] == list(
        domains_service.WEBSITE_MODES
    )
    assert by_domain["exemple.fr"]["default_mode"] == domains_service.MODE_PARKING
    # A non-conformant one may only redirect, or serve nothing.
    assert by_domain["exemple.com"]["allowed_modes"] == list(
        domains_service.MODES_WITHOUT_RPNT_1_2
    )
    assert by_domain["exemple.com"]["default_mode"] == domains_service.MODE_NONE


def test_dns_timeout_budgets_stay_under_the_platform_limit():
    """The check must fail on its own terms, never on the router's.

    The platform router closes a connection at 30s, so a request has to finish
    under 25s.
    Each budget fails inside the next one, so the user gets our own message rather
    than a platform error — and a lookup is never cut off while still inside its
    own budget.
    """
    per_query = settings.DOMAINS_DNS_TIMEOUT
    per_name = settings.DOMAINS_DNS_MAX_RESOLUTION_TIME
    request_budget = 25.0

    assert per_query < per_name, "a name is several queries"
    assert per_name < dns_service.BATCH_TIMEOUT, (
        "the batch would cut off a lookup still inside its own budget"
    )
    assert dns_service.BATCH_TIMEOUT <= request_budget, (
        "the platform would kill the request before the batch deadline fires"
    )
