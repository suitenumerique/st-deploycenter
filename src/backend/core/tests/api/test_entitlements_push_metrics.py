# pylint: disable=invalid-name
"""
Test pushing usage metrics in the body of POST /entitlements.

Callers can provide the usage metrics the endpoint would otherwise scrape
over HTTP. Each pushed account type suppresses the corresponding scrape.
"""

import pytest
import responses
from responses import matchers
from rest_framework.test import APIClient

from core import factories, models
from core.tests.utils import assert_equals_partial

pytestmark = pytest.mark.django_db

# pylint: disable=assignment-from-none
# pylint: disable=duplicate-code

METRICS_USAGE_ENDPOINT = "https://fichiers.suite.anct.gouv.fr/metrics/usage"
SIRET = "12345678900001"

PUSHED_USER_ITEM = {
    "siret": SIRET,
    "account": {"type": "user", "id": "xyz", "email": "test@example.com"},
    "metrics": {"storage_used": 700},
}
PUSHED_ORGANIZATION_ITEM = {
    "siret": SIRET,
    "account": {"type": "organization"},
    "metrics": {"storage_used": 1500},
}


def _setup_drive_subscription(is_active=True):
    """Create an organization with a drive subscription and its default entitlements."""
    organization = factories.OrganizationFactory(siret=SIRET)
    operator = factories.OperatorFactory()
    factories.OperatorOrganizationRoleFactory(
        operator=operator, organization=organization
    )
    service = factories.ServiceFactory(
        type="drive",
        config={
            "entitlements_api_key": "test_token",
            "usage_metrics_endpoint": METRICS_USAGE_ENDPOINT,
            "metrics_auth_token": "test_token",
        },
    )
    factories.ServiceSubscriptionFactory(
        organization=organization,
        service=service,
        operator=operator,
        is_active=is_active,
    )
    return organization, operator, service


def _register_scrape_mocks():
    """Register the account and organization usage metrics scrape mocks.

    Scrape errors are swallowed by scrape_service_usage_metrics, so whether
    the view scraped must be asserted via each mock's call_count.
    """
    user_mock = responses.add(
        responses.GET,
        METRICS_USAGE_ENDPOINT,
        match=[
            matchers.query_param_matcher(
                {
                    "account_type": "user",
                    "account_id_value": "xyz",
                    "limit": 1000,
                    "offset": 0,
                }
            )
        ],
        json={
            "count": 1,
            "results": [
                {
                    "siret": SIRET,
                    "account": {
                        "type": "user",
                        "id": "xyz",
                        "email": "test@example.com",
                    },
                    "metrics": {"storage_used": 500},
                }
            ],
        },
        status=200,
    )
    organization_mock = responses.add(
        responses.GET,
        METRICS_USAGE_ENDPOINT,
        match=[
            matchers.query_param_matcher(
                {
                    "account_type": "organization",
                    "account_id_key": "siret",
                    "account_id_value": SIRET,
                    "limit": 1000,
                    "offset": 0,
                }
            )
        ],
        json={
            "count": 1,
            "results": [
                {
                    "siret": SIRET,
                    "account": {"type": "organization"},
                    "metrics": {"storage_used": 1000},
                }
            ],
        },
        status=200,
    )
    return user_mock, organization_mock


def _post_entitlements(service, siret, body=None, token="test_token"):
    """POST /entitlements with the same query params as the GET flavor."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)
    return client.post(
        "/api/v1.0/entitlements/",
        data=body,
        format="json",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": siret,
        },
        headers={"X-Service-Auth": f"Bearer {token}"},
    )


def _get_stored_value(service, organization, account_type, external_id):
    """Return the stored metric value for the given account, or None."""
    metric = models.Metric.objects.filter(
        service=service,
        organization=organization,
        account__type=account_type,
        account__external_id=external_id,
    ).first()
    return metric.value if metric else None


@responses.activate
@pytest.mark.parametrize("body", [None, {}, {"usage_metrics": []}])
def test_api_entitlements_post_without_metrics_matches_get(body):
    """POST without pushed metrics must behave exactly like GET: both scrapes run."""
    organization, operator, service = _setup_drive_subscription()
    user_mock, organization_mock = _register_scrape_mocks()

    response = _post_entitlements(service, organization.siret, body=body)

    assert response.status_code == 200
    assert user_mock.call_count == 1
    assert organization_mock.call_count == 1
    assert_equals_partial(
        response.json(),
        {
            "operator": {
                "id": str(operator.id),
                "name": operator.name,
            },
            "entitlements": {
                "can_access": True,
                "can_upload": True,
                "can_upload_resolve_level": "user",
                "max_storage_account": 1000 * 1000 * 1000 * 5,
                "max_storage_organization": 1000 * 1000 * 1000 * 10,
            },
            "metrics": {
                "account": {"storage_used": 500},
                "organization": {"storage_used": 1000},
            },
        },
    )
    assert _get_stored_value(service, organization, "user", "xyz") == 500
    assert (
        _get_stored_value(service, organization, "organization", organization.siret)
        == 1000
    )


@responses.activate
def test_api_entitlements_post_with_all_metrics_skips_all_scrapes():
    """Pushing both user and organization metrics must avoid any HTTP scrape."""
    organization, _operator, service = _setup_drive_subscription()
    user_mock, organization_mock = _register_scrape_mocks()

    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [PUSHED_USER_ITEM, PUSHED_ORGANIZATION_ITEM]},
    )

    assert response.status_code == 200
    assert user_mock.call_count == 0
    assert organization_mock.call_count == 0
    assert_equals_partial(
        response.json(),
        {
            "entitlements": {
                "can_access": True,
                "can_upload": True,
                "can_upload_resolve_level": "user",
            },
            "metrics": {
                "account": {"storage_used": 700},
                "organization": {"storage_used": 1500},
            },
        },
    )

    # Pushed metrics are stored exactly like scraped ones.
    metric_user = models.Metric.objects.get(
        service=service,
        organization=organization,
        account__type="user",
        account__external_id="xyz",
    )
    assert metric_user.key == "storage_used"
    assert metric_user.value == 700
    assert metric_user.account.email == "test@example.com"

    # The organization account is created with the siret as external_id,
    # like the scrape path does when the item has no account id.
    metric_organization = models.Metric.objects.get(
        service=service,
        organization=organization,
        account__type="organization",
        account__external_id=organization.siret,
    )
    assert metric_organization.key == "storage_used"
    assert metric_organization.value == 1500


@responses.activate
def test_api_entitlements_post_pushed_metrics_drive_resolution():
    """Entitlements must be resolved from the pushed values (organization full here)."""
    organization, _operator, service = _setup_drive_subscription()
    user_mock, organization_mock = _register_scrape_mocks()

    over_quota_organization_item = {
        **PUSHED_ORGANIZATION_ITEM,
        "metrics": {"storage_used": 1000 * 1000 * 1000 * 11},
    }
    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [PUSHED_USER_ITEM, over_quota_organization_item]},
    )

    assert response.status_code == 200
    assert user_mock.call_count == 0
    assert organization_mock.call_count == 0
    assert_equals_partial(
        response.json(),
        {
            "entitlements": {
                "can_upload": False,
                "can_upload_resolve_level": "organization",
            },
        },
    )


@responses.activate
def test_api_entitlements_post_with_user_metrics_still_scrapes_organization():
    """Pushing only user metrics must leave the organization scrape untouched."""
    organization, _operator, service = _setup_drive_subscription()
    user_mock, organization_mock = _register_scrape_mocks()

    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [PUSHED_USER_ITEM]},
    )

    assert response.status_code == 200
    assert user_mock.call_count == 0
    assert organization_mock.call_count == 1
    assert_equals_partial(
        response.json(),
        {
            "metrics": {
                "account": {"storage_used": 700},
                "organization": {"storage_used": 1000},
            },
        },
    )


@responses.activate
def test_api_entitlements_post_with_organization_metrics_still_scrapes_account():
    """Pushing only organization metrics must leave the account scrape untouched."""
    organization, _operator, service = _setup_drive_subscription()
    user_mock, organization_mock = _register_scrape_mocks()

    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [PUSHED_ORGANIZATION_ITEM]},
    )

    assert response.status_code == 200
    assert user_mock.call_count == 1
    assert organization_mock.call_count == 0
    assert_equals_partial(
        response.json(),
        {
            "metrics": {
                "account": {"storage_used": 500},
                "organization": {"storage_used": 1500},
            },
        },
    )


@responses.activate
@pytest.mark.parametrize(
    "body",
    [
        {"usage_metrics": "nope"},
        {"usage_metrics": [123]},
        {"usage_metrics": [{"siret": SIRET, "account": "user", "metrics": {}}]},
        {"usage_metrics": [{"siret": SIRET, "metrics": "x"}]},
    ],
)
def test_api_entitlements_post_malformed_body(body):
    """Malformed bodies must be rejected with a 400 before anything is stored."""
    organization, _operator, service = _setup_drive_subscription()

    response = _post_entitlements(service, organization.siret, body=body)

    assert response.status_code == 400
    assert not models.Metric.objects.exists()


@responses.activate
def test_api_entitlements_post_inactive_subscription_stores_nothing():
    """Without an active subscription, pushed metrics are ignored, like scrapes."""
    organization, _operator, service = _setup_drive_subscription(is_active=False)

    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [PUSHED_USER_ITEM, PUSHED_ORGANIZATION_ITEM]},
    )

    assert response.status_code == 200
    assert not models.Metric.objects.exists()


@responses.activate
def test_api_entitlements_post_unknown_siret_item_is_skipped():
    """An item for an unknown organization is skipped but still covers its scope."""
    organization, _operator, service = _setup_drive_subscription()
    user_mock, organization_mock = _register_scrape_mocks()

    unknown_siret_item = {**PUSHED_USER_ITEM, "siret": "99999999999999"}
    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [unknown_siret_item]},
    )

    assert response.status_code == 200
    # The caller asserted it pushed the user scope, so no account scrape.
    assert user_mock.call_count == 0
    assert organization_mock.call_count == 1
    # The unresolvable item was skipped, nothing stored for the user.
    assert _get_stored_value(service, organization, "user", "xyz") is None


@responses.activate
def test_api_entitlements_post_authentication():
    """POST must enforce the same service authentication as GET."""
    organization, _operator, service = _setup_drive_subscription()

    response = _post_entitlements(
        service,
        organization.siret,
        body={"usage_metrics": [PUSHED_USER_ITEM]},
        token="wrong_token",
    )
    assert response.status_code == 403
    assert not models.Metric.objects.exists()

    client = APIClient()
    response = client.post(
        "/api/v1.0/entitlements/",
        data={"usage_metrics": [PUSHED_USER_ITEM]},
        format="json",
        query_params={
            "service_id": service.id,
            "account_type": "user",
            "account_id": "xyz",
            "siret": organization.siret,
        },
    )
    assert response.status_code == 401
    assert not models.Metric.objects.exists()
