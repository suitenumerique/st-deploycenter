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

from django.db import connection


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


def _acquire(key: int) -> None:
    """Take one transaction-scoped advisory lock."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def lock_domains(domains) -> None:
    """Serialize "is this domain already claimed?" checks across transactions.

    Used by both features that make a domain exclusive: ProConnect routing and the
    domains service. They share the lock namespace on purpose — the same string
    cannot be claimed twice, whichever of the two is claiming it.

    Taken in sorted order so concurrent writers cannot build a deadlock cycle.
    """
    for domain in sorted(set(domains)):
        _acquire(advisory_lock_key("domain", domain))


def lock_idp(idp_id: str) -> None:
    """Serialize the ProConnect pushes of one provider across processes.

    The push is a full replace computed from the DB, so two overlapping writers
    lose an update: the one that reads first can push *last* and drop the other's
    domain, with no error anywhere. The lock is held until the caller's outermost
    transaction commits, so the read, the PATCH and the commit are one critical
    section per idp.
    """
    _acquire(advisory_lock_key(idp_id))
