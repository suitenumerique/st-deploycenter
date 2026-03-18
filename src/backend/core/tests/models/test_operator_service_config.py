"""Tests for OperatorServiceConfig model."""

import pytest

from core import factories
from core.models import OperatorServiceConfig


@pytest.mark.django_db
class TestGetEffectiveConfig:
    """Tests for OperatorServiceConfig.get_effective_config."""

    def test_no_override_returns_service_config(self):
        """When config_override is empty, effective config equals service config."""
        service = factories.ServiceFactory(
            config={"metrics_endpoint": "https://example.com", "auth_token": "abc"}
        )
        osc = factories.OperatorServiceConfigFactory(
            service=service, config_override={}
        )
        assert osc.get_effective_config() == {
            "metrics_endpoint": "https://example.com",
            "auth_token": "abc",
        }

    def test_override_replaces_existing_keys(self):
        """Override keys take precedence over service config keys."""
        service = factories.ServiceFactory(
            config={"metrics_endpoint": "https://base.com", "timeout": 30}
        )
        osc = factories.OperatorServiceConfigFactory(
            service=service,
            config_override={"metrics_endpoint": "https://override.com"},
        )
        result = osc.get_effective_config()
        assert result["metrics_endpoint"] == "https://override.com"
        assert result["timeout"] == 30

    def test_override_adds_new_keys(self):
        """Override can add keys not present in the base service config."""
        service = factories.ServiceFactory(config={"key1": "val1"})
        osc = factories.OperatorServiceConfigFactory(
            service=service, config_override={"key2": "val2"}
        )
        result = osc.get_effective_config()
        assert result == {"key1": "val1", "key2": "val2"}

    def test_both_empty(self):
        """Both configs empty returns empty dict."""
        service = factories.ServiceFactory(config={})
        osc = factories.OperatorServiceConfigFactory(
            service=service, config_override={}
        )
        assert osc.get_effective_config() == {}

    def test_service_config_none(self):
        """Handles None service config gracefully."""
        service = factories.ServiceFactory(config=None)
        osc = factories.OperatorServiceConfigFactory(
            service=service, config_override={"key": "value"}
        )
        assert osc.get_effective_config() == {"key": "value"}

    def test_override_none(self):
        """Handles None config_override gracefully."""
        service = factories.ServiceFactory(config={"key": "value"})
        osc = factories.OperatorServiceConfigFactory(service=service)
        osc.config_override = None
        assert osc.get_effective_config() == {"key": "value"}

    def test_does_not_mutate_service_config(self):
        """get_effective_config should not modify the original service config."""
        original = {"key": "original"}
        service = factories.ServiceFactory(config=original)
        osc = factories.OperatorServiceConfigFactory(
            service=service, config_override={"key": "overridden"}
        )
        osc.get_effective_config()
        assert service.config == {"key": "original"}

    def test_nested_values_are_replaced_not_deep_merged(self):
        """Override does a shallow merge — nested dicts are replaced entirely."""
        service = factories.ServiceFactory(config={"nested": {"a": 1, "b": 2}})
        osc = factories.OperatorServiceConfigFactory(
            service=service, config_override={"nested": {"a": 99}}
        )
        result = osc.get_effective_config()
        assert result["nested"] == {"a": 99}


@pytest.mark.django_db
class TestGetEffectiveServiceConfig:
    """Tests for OperatorServiceConfig.get_effective_service_config classmethod."""

    def test_no_operator_returns_service_config(self):
        """When operator is None, returns plain service config."""
        service = factories.ServiceFactory(config={"key": "base"})
        result = OperatorServiceConfig.get_effective_service_config(service, None)
        assert result == {"key": "base"}

    def test_no_osc_exists_returns_service_config(self):
        """When no OperatorServiceConfig exists for the pair, returns service config."""
        service = factories.ServiceFactory(config={"key": "base"})
        operator = factories.OperatorFactory()
        result = OperatorServiceConfig.get_effective_service_config(service, operator)
        assert result == {"key": "base"}

    def test_osc_exists_returns_merged_config(self):
        """When an OperatorServiceConfig exists, returns merged config."""
        service = factories.ServiceFactory(config={"key": "base", "other": "value"})
        operator = factories.OperatorFactory()
        factories.OperatorServiceConfigFactory(
            service=service,
            operator=operator,
            config_override={"key": "overridden"},
        )
        result = OperatorServiceConfig.get_effective_service_config(service, operator)
        assert result == {"key": "overridden", "other": "value"}

    def test_service_config_none_no_operator(self):
        """Handles None service config with no operator."""
        service = factories.ServiceFactory(config=None)
        result = OperatorServiceConfig.get_effective_service_config(service, None)
        assert result == {}

    def test_returns_copy_not_reference(self):
        """Returned dict should be a new dict, not a reference to service.config."""
        service = factories.ServiceFactory(config={"key": "value"})
        result = OperatorServiceConfig.get_effective_service_config(service, None)
        result["key"] = "mutated"
        assert service.config == {"key": "value"}


@pytest.mark.django_db
class TestSubscriptionGetEffectiveServiceConfig:
    """Tests for ServiceSubscription.get_effective_service_config."""

    def test_delegates_to_operator_service_config(self):
        """Subscription method returns merged config using its operator."""
        service = factories.ServiceFactory(config={"key": "base", "other": "val"})
        operator = factories.OperatorFactory()
        factories.OperatorServiceConfigFactory(
            service=service,
            operator=operator,
            config_override={"key": "overridden"},
        )
        organization = factories.OrganizationFactory()
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization
        )
        sub = factories.ServiceSubscriptionFactory(
            service=service, operator=operator, organization=organization
        )
        result = sub.get_effective_service_config()
        assert result == {"key": "overridden", "other": "val"}

    def test_no_osc_returns_service_config(self):
        """When no OperatorServiceConfig exists, returns plain service config."""
        service = factories.ServiceFactory(config={"key": "base"})
        operator = factories.OperatorFactory()
        organization = factories.OrganizationFactory()
        factories.OperatorOrganizationRoleFactory(
            operator=operator, organization=organization
        )
        sub = factories.ServiceSubscriptionFactory(
            service=service, operator=operator, organization=organization
        )
        assert sub.get_effective_service_config() == {"key": "base"}
