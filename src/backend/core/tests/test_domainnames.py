"""Tests for the domain name rules (core/services/domainnames.py)."""

import pytest

from core.services.domainnames import (
    invalid_domains,
    is_valid_domain,
    normalize_domains,
)

LABEL_63 = "a" * 63


@pytest.mark.parametrize(
    "domain",
    [
        "commune.fr",
        "  Mairie.Commune.FR ",
        "xn--exemple-9ua.fr",
        "a-b.fr",
        f"{LABEL_63}.fr",
        # 253 characters: the longest name there is.
        ".".join([LABEL_63] * 3 + ["a" * 61]),
    ],
)
def test_is_valid_domain_accepts_real_names(domain):
    """Well-formed names pass, whatever the case or surrounding spaces."""
    assert is_valid_domain(domain)


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "fr",
        "pas un domaine",
        "-a.fr",
        "a-.fr",
        "a..fr",
        "a_b.fr",
        None,
        # Over the DNS limits api-partenaires enforces: 64-character label...
        f"{LABEL_63}a.fr",
        # ... and 254 characters in all.
        ".".join([LABEL_63] * 3 + ["a" * 62]),
    ],
)
def test_is_valid_domain_refuses_the_rest(domain):
    """Anything api-partenaires would answer 400 to is refused here first."""
    assert not is_valid_domain(domain)


def test_overlong_domains_are_reported_and_dropped():
    """The write paths 400 on them, and normalization never stores one."""
    too_long = f"{LABEL_63}a.fr"
    assert invalid_domains(["ok.fr", too_long]) == [too_long]
    assert normalize_domains(["ok.fr", too_long]) == ["ok.fr"]
