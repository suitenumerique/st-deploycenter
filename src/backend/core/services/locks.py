"""Postgres advisory locks, for the things a row lock cannot cover.

``SELECT ... FOR UPDATE`` can only lock rows that already exist: two transactions
claiming the same *new* domain both find no conflict and both commit. Locking the
value itself closes that phantom write — the second transaction waits, then
re-reads (READ COMMITTED) and sees the first one's row.

Locks are transaction-scoped (released on commit/rollback) and are no-ops outside
PostgreSQL, so the test suite and sqlite runs behave normally.

**Deadlock rule**: a caller taking several locks takes them in this order —
domains (sorted) first, then the idp — and never the reverse.
"""

import hashlib
import time

from django.db import connection

# How often a bounded wait asks again.
LOCK_POLL_INTERVAL = 0.1


class LockTimeout(Exception):
    """A bounded wait for an advisory lock ran out."""


def advisory_lock_key(*parts: str) -> int:
    """Stable signed 64-bit key for ``pg_advisory_xact_lock``.

    Must not use ``hash()``: it is salted per process, so two web workers would
    derive different keys for the same object and never exclude each other.
    """
    return int.from_bytes(
        hashlib.sha256("\0".join(parts).encode("utf-8")).digest()[:8],
        "big",
        signed=True,
    )


def _acquire(key: int, timeout: float | None = None) -> None:
    """Take one transaction-scoped advisory lock.

    Waits as long as it takes, or at most ``timeout`` seconds when given (then
    raises :class:`LockTimeout`).
    """
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        if timeout is None:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
            return
        deadline = time.monotonic() + timeout
        while True:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
            if cursor.fetchone()[0]:
                return
            if time.monotonic() >= deadline:
                raise LockTimeout(f"advisory lock {key} not available")
            time.sleep(LOCK_POLL_INTERVAL)


def lock_domains(domains) -> None:
    """Serialize "is this domain already claimed?" checks across transactions.

    Used by both features that make a domain exclusive: ProConnect routing and the
    domains service. They share the lock namespace on purpose — the same string
    cannot be claimed twice, whichever of the two is claiming it.

    Taken in sorted order so concurrent writers cannot build a deadlock cycle.
    """
    for domain in sorted(set(domains)):
        _acquire(advisory_lock_key("domain", domain))


def lock_idp(idp_id: str, timeout: float | None = None) -> None:
    """Serialize the ProConnect pushes of one provider across processes.

    A reconciliation reads the provider, then detaches what the DB does not route.
    Without the lock it would detach a domain that a concurrent request has just
    attached and not committed yet. The lock is held until the caller's outermost
    transaction commits, so the calls and the commit are one critical section per
    idp.

    A request passes a ``timeout`` so it never queues behind a long batch push.
    """
    _acquire(advisory_lock_key(idp_id), timeout)
