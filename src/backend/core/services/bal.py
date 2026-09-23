"""Helpers and constants for the BAL (Base Adresse Locale) service.

BAL is a service for administrating communes' official addresses. The
entitlements API exposes ``can_admin_communes``: a dict of
``insee: [channels]`` describing the communes (and address channels) the
queried user may administer.

Only communes appear as keys (never EPCIs), and every covered commune must
have an active BAL subscription.
"""

from core import models

SERVICE_TYPE = "bal"

# The address channels a commune exposes for administration.
CHANNELS = [
    "channel_api_depot",
    "channel_moissonneur",
    "channel_mesadresses",
    "channel_formulaire",
]

# Key in a commune's BAL subscription metadata: whether the EPCI it belongs to
# may administer its addresses. Absent means allowed.
EPCI_DELEGATION_KEY = "epci_delegation"

# Key in a BAL admin AccountServiceLink scope: {"channels": [channels]}, the
# channels granted on every commune the account's organization covers. An
# empty scope means all channels.
SCOPE_CHANNELS_KEY = "channels"


def epci_delegation_allowed(metadata):
    """Whether a commune's BAL subscription metadata lets its EPCI administer
    its addresses."""
    return (metadata or {}).get(EPCI_DELEGATION_KEY, True) is not False


def get_covered_communes(organization, service):
    """Return the INSEE codes of the communes an organization covers through
    its active BAL subscription.

    A commune covers itself. An EPCI covers its member communes that have an
    active BAL subscription and have not opted out of delegation. Other
    organization types cover nothing.
    """
    if organization.type not in ("commune", "epci"):
        return set()

    if not models.ServiceSubscription.objects.filter(
        organization=organization, service=service, is_active=True
    ).exists():
        return set()

    if organization.type == "commune":
        return {organization.code_insee} if organization.code_insee else set()

    # Without this guard, a null siren would match every commune whose
    # epci_siren is null.
    if not organization.siren:
        return set()
    members = models.ServiceSubscription.objects.filter(
        organization__type="commune",
        organization__epci_siren=organization.siren,
        service=service,
        is_active=True,
    ).values_list("organization__code_insee", "metadata")
    return {
        insee
        for insee, metadata in members
        if insee and epci_delegation_allowed(metadata)
    }


def parse_scope(scope):
    """Return the set of channels a BAL AccountServiceLink scope grants.

    An empty scope grants all channels. A malformed scope grants nothing.
    """
    if not scope:
        return set(CHANNELS)
    channels = scope.get(SCOPE_CHANNELS_KEY) if isinstance(scope, dict) else None
    if not isinstance(channels, list):
        return set()
    return {c for c in channels if c in CHANNELS}


def validate_scope(scope):
    """Raise ValueError when a BAL AccountServiceLink scope is malformed.

    Accepts an empty scope or ``{"channels": [...]}`` with at least one channel.
    """
    if scope == {}:
        return
    channels = scope.get(SCOPE_CHANNELS_KEY) if isinstance(scope, dict) else None
    if (
        not isinstance(scope, dict)
        or set(scope) != {SCOPE_CHANNELS_KEY}
        or not isinstance(channels, list)
        or not channels
        or any(c not in CHANNELS for c in channels)
    ):
        raise ValueError(
            f"Scope must be empty or {{'{SCOPE_CHANNELS_KEY}': [...]}} with at "
            f"least one of: {', '.join(CHANNELS)}."
        )
