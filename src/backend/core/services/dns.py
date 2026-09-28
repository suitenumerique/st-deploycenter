"""Authoritative DNS lookups, used by the domains service to check delegations.

Resolution walks the delegation chain from the root with ``recursive-resolver``
instead of asking whatever is in ``/etc/resolv.conf``, so a check reads what the
authoritative servers publish rather than what an intermediate cache decided to
remember. Each batch gets its own resolver and cache: a delegation the user just
changed at their registrar shows up on the next check, while within the batch each
nameserver hostname is resolved once. Without that cache a chain of nameservers
living outside the zones they serve (houdelaincourt.fr -> lst-domaines.fr ->
scw.cloud -> online.net -> scaleway.com) is re-resolved at every level and runs out
of the resolver's query budget.

DNSSEC validation is off: we read public delegation data to display a hint in the
UI, not a credential, and a bogus zone should surface as "nameservers don't match"
rather than as an error the user cannot act on.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, wait

from django.conf import settings

from recursive_resolver import (
    NoAnswerError,
    NXDOMAINError,
    RecursiveResolver,
    ResolutionTimeoutError,
    ResolverError,
)

logger = logging.getLogger(__name__)

# Why a check has no nameservers to show, in the order the UI cares about.
ERROR_NXDOMAIN = "nxdomain"  # the name is not registered
ERROR_NOT_DELEGATED = "not_delegated"  # registered, but no NS records
ERROR_TIMEOUT = "timeout"  # nameservers unreachable, or we ran out of time
ERROR_UNKNOWN = "error"  # anything else (SERVFAIL, budget, malformed zone…)

# Domains are resolved concurrently: a check covers a whole subscription and the
# lookups are independent. Kept small — each worker holds an open socket.
MAX_WORKERS = 8

# Wall-clock budget for one batch. A domain not resolved by then is reported as a
# timeout rather than keeping the request open: an unreachable nameserver costs the
# full per-query timeout on every retry, and a modal must not hang on it.
#
# The ceiling is the platform router, which closes the connection at 30s — so a
# request has to finish under 25s, or the caller gets a platform error instead of
# our own "vérification impossible" result. Budgets are strictly nested, each one
# failing inside the next so the error is always the specific one:
#
#     per query (5s) < per name (15s) < batch (20s) < request target (25s) < 30s
#
# Raising DOMAINS_DNS_MAX_RESOLUTION_TIME above this leaves the batch cutting off
# lookups that were still inside their own budget.
BATCH_TIMEOUT = 20.0


def new_resolver() -> RecursiveResolver:
    """A resolver for one batch, caching every answer and zone cut it sees.

    Thread-safe: the batch's workers share it, and its cache.
    """
    return RecursiveResolver(
        timeout=settings.DOMAINS_DNS_TIMEOUT,
        max_resolution_time=settings.DOMAINS_DNS_MAX_RESOLUTION_TIME,
        max_delegation_cache_depth="all",
        cache_answers=True,
        dnssec=False,
    )


def nameservers(
    resolver: RecursiveResolver, domain: str
) -> tuple[list[str], str | None]:
    """Return ``(nameservers, error)`` for a domain's NS records.

    The names are lowercased and stripped of their trailing dot, sorted. On failure
    the list is empty and ``error`` is one of the ``ERROR_*`` codes above.
    """
    try:
        records = resolver.resolve(domain, "NS")
    except NXDOMAINError:
        return [], ERROR_NXDOMAIN
    except NoAnswerError:
        return [], ERROR_NOT_DELEGATED
    except ResolutionTimeoutError:
        return [], ERROR_TIMEOUT
    except ResolverError as error:
        logger.info("DNS check failed for %s: %s", domain, error)
        return [], ERROR_UNKNOWN

    found = sorted({record.strip().rstrip(".").lower() for record in records if record})
    # An empty NS rrset is not something an authoritative server should return, but
    # reporting "delegated to nothing" as a success would show a green checkmark.
    return (found, None) if found else ([], ERROR_NOT_DELEGATED)


def nameservers_batch(domains: list[str]) -> dict[str, tuple[list[str], str | None]]:
    """Resolve the NS records of several domains concurrently.

    Every domain gets an entry; the ones still running when :data:`BATCH_TIMEOUT`
    elapses are reported as timed out.
    """
    if not domains:
        return {}

    resolver = new_resolver()
    results: dict[str, tuple[list[str], str | None]] = {}
    # Not a context manager: leaving one waits for every running lookup, which would
    # defeat the batch deadline below.
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = {
            pool.submit(nameservers, resolver, domain): domain for domain in domains
        }
        done, pending = wait(futures, timeout=BATCH_TIMEOUT)
        for future in pending:
            results[futures[future]] = ([], ERROR_TIMEOUT)
        for future in done:
            domain = futures[future]
            try:
                results[domain] = future.result()
            except Exception:  # pylint: disable=broad-except
                logger.exception("DNS check crashed for %s", domain)
                results[domain] = ([], ERROR_UNKNOWN)
    finally:
        # Drops what has not started; a lookup already in flight finishes on its own
        # resolution deadline, we just stop waiting for it.
        pool.shutdown(wait=False, cancel_futures=True)
    return results
