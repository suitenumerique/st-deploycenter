"""Tests for the candidate-domain generator (core/services/domains_candidates.py).

The expected sets are exhaustive on purpose: a rule that starts proposing more than
it should is a regression, since every candidate is a suggestion shown to a
collectivité.
"""

import uuid

import pytest

from core.models import Organization
from core.services.domains_candidates import (
    candidate_domains_for_organization,
    slugify_org_domain,
)


def _commune(name, dept=None, dpnt=None):
    """A transient commune — the generator never touches the database."""
    return Organization(
        type="commune",
        name=name,
        departement_code_insee=dept,
        proconnect_domains={"dpnt": dpnt or []},
    )


def test_slugify_org_domain():
    """Accents and spaces are normalized; an empty name yields nothing."""
    assert slugify_org_domain("Castellet-en-Luberon") == "castellet-en-luberon.fr"
    assert (
        slugify_org_domain("Saint-Étienne du Rouvray") == "saint-etienne-du-rouvray.fr"
    )
    assert slugify_org_domain("") is None


def test_only_communes_get_candidates():
    """The name rules were measured on communes, so other types get nothing."""
    org = Organization(type="epci", name="CC des Collines", proconnect_domains={})
    assert candidate_domains_for_organization(org) == []


def test_unhyphenated_name_has_no_flat_variant():
    """Nothing to flatten, so the list stays the original four forms."""
    assert set(candidate_domains_for_organization(_commune("Aiglun", "06"))) == {
        "aiglun.fr",
        "aiglun06.fr",
        "mairie-aiglun.fr",
        "ville-aiglun.fr",
    }


def test_hyphenated_name_adds_the_flat_spelling():
    """The hyphenless spelling, and its mairie-/ville- forms, on top of the originals."""
    assert set(
        candidate_domains_for_organization(_commune("Château-Gaillard", "01"))
    ) == {
        # original, hyphenated forms
        "chateau-gaillard.fr",
        "chateau-gaillard01.fr",
        "mairie-chateau-gaillard.fr",
        "ville-chateau-gaillard.fr",
        # hyphenless alternatives
        "chateaugaillard.fr",
        "mairie-chateaugaillard.fr",
        "ville-chateaugaillard.fr",
        "chateaugaillard01.fr",
    }


def test_flat_spelling_carries_the_departement_number():
    """Best ratio of the lot: many communes registered {name}{dept} run together."""
    candidates = candidate_domains_for_organization(
        _commune("Neuville-les-Dames", "01")
    )
    assert "neuvillelesdames01.fr" in candidates
    # The hyphenated form with the number is still there too.
    assert "neuville-les-dames01.fr" in candidates


def test_saint_is_abbreviated_to_st():
    """saint- is written st- about as often as not, hyphenated or run together."""
    candidates = set(candidate_domains_for_organization(_commune("Saint-Rémy", "01")))
    assert {"saint-remy.fr", "st-remy.fr", "stremy.fr", "saintremy.fr"} <= candidates


def test_sainte_is_abbreviated_to_ste():
    """Same rule as saint-/st-, with the feminine form kept distinct."""
    candidates = set(
        candidate_domains_for_organization(_commune("Sainte-Colombe", "69"))
    )
    assert {"sainte-colombe.fr", "ste-colombe.fr", "stecolombe.fr"} <= candidates


def test_inner_saint_is_abbreviated_too():
    """The abbreviation applies mid-name, not only at the start."""
    candidates = set(
        candidate_domains_for_organization(_commune("Bazoches-et-Saint-Thibaut", "02"))
    )
    assert "bazoches-et-st-thibaut.fr" in candidates
    assert "bazochesetstthibaut.fr" in candidates


def test_leading_apostrophe_article_is_dropped():
    """slugify glues "L'" to the next word, so the article is stripped from the name."""
    candidates = set(
        candidate_domains_for_organization(_commune("L'Abergement-de-Varey", "01"))
    )
    assert {
        # what slugify produces, article glued on
        "labergement-de-varey.fr",
        # and the forms without it
        "abergement-de-varey.fr",
        "abergementdevarey.fr",
    } <= candidates


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Les Échelles", "echelles.fr"),
        ("La Chapelle", "chapelle.fr"),
        ("Le Pin", "pin.fr"),
    ],
)
def test_every_article_form_is_handled(name, expected):
    """Every leading article form is stripped, not just the longest one."""
    assert expected in candidate_domains_for_organization(_commune(name, "73"))


def test_regional_extension_applies_to_both_spellings():
    """A Breton commune gets .bzh on the hyphenated name and on the flat one."""
    candidates = set(candidate_domains_for_organization(_commune("Plouézoch", "29")))
    assert "plouezoch.bzh" in candidates

    candidates = set(candidate_domains_for_organization(_commune("Saint-Malo", "35")))
    assert {"saint-malo.bzh", "saintmalo.bzh"} <= candidates


def test_regional_extension_stays_in_its_departements():
    """.bzh is not proposed outside Bretagne."""
    candidates = candidate_domains_for_organization(_commune("Saint-Malo", "45"))
    assert not [d for d in candidates if d.endswith(".bzh")]


def test_no_alternatives_when_dila_already_has_the_canonical_domain():
    """A collectivité with its official {slug}.fr needs no suggested spellings."""
    org = _commune("Château-Gaillard", "01", dpnt=["chateau-gaillard.fr"])
    # Only the nationwide/regional {slug}.<ext> forms remain, minus the DILA domain.
    assert candidate_domains_for_organization(org) == []


def test_dila_domains_are_never_proposed():
    """A domain the org already holds is dropped from the suggestions."""
    org = _commune("Château-Gaillard", "01", dpnt=["chateaugaillard.fr"])
    candidates = candidate_domains_for_organization(org)
    assert "chateaugaillard.fr" not in candidates
    # The rest of the alternatives are still offered.
    assert "chateau-gaillard.fr" in candidates


def test_mairie_form_of_the_article_less_name_is_not_proposed():
    """Measured on the DPNT dataset: it hit a neighbour twice as often as the org."""
    candidates = candidate_domains_for_organization(_commune("La Chapelle", "73"))
    assert "mairie-chapelle.fr" not in candidates
    # The bare and hyphenless forms are still there.
    assert "chapelle.fr" in candidates


def test_claimed_domains_of_another_org_are_not_proposed():
    """A homonym's real domain must never be suggested to a different commune."""
    org = _commune("Sainte-Colombe", "69")
    org.pk = uuid.UUID("11111111-1111-1111-1111-111111111111")
    claimed = {"sainte-colombe.fr": uuid.UUID("22222222-2222-2222-2222-222222222222")}

    candidates = candidate_domains_for_organization(org, claimed)
    assert "sainte-colombe.fr" not in candidates
    # Everything the other org does not own is still proposed.
    assert "saintecolombe.fr" in candidates
    assert "ste-colombe.fr" in candidates


def test_an_org_own_claimed_domain_is_still_proposed():
    """The filter is about *other* collectivités, not about the org itself."""
    org = _commune("Sainte-Colombe", "69")
    org.pk = uuid.UUID("11111111-1111-1111-1111-111111111111")
    claimed = {"sainte-colombe.fr": org.pk}

    assert "sainte-colombe.fr" in candidate_domains_for_organization(org, claimed)


def test_claimed_map_is_optional():
    """Callers that have no ownership map still get candidates."""
    assert candidate_domains_for_organization(_commune("Aiglun", "06"))
