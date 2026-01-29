# Account Data Model

## Overview

An **Account** represents an entity (user, mailbox, etc.) within an organization. Accounts are the link between external identities and the deploy center's metrics and entitlements systems.

Each account belongs to exactly one organization and has a **type** (e.g. `user`, `mailbox`) that determines its role in entitlement resolution.

## Fields

| Field | Description |
|---|---|
| `email` | Email address, known early by operators |
| `external_id` | External identifier (e.g. OIDC `sub` claim from SSO), known by services |
| `type` | Account type (`user`, `mailbox`, etc.) |
| `organization` | Parent organization (FK) |
| `roles` | JSON array of role strings |

## Identifiers and the Chicken/Egg Problem

Accounts have two identifiers that arrive from different sources at different times:

| Source | Knows | Creates account with |
|---|---|---|
| **Operator** (management API) | email only | `external_id=""`, `email="alice@org.fr"` |
| **Service** (metrics scraping) | external_id + email | `external_id="oidc-sub-123"`, `email="alice@org.fr"` |

The operator creates accounts before users ever log in to a service (e.g. provisioning from an HR directory). At that point, the OIDC `sub` (used as `external_id`) doesn't exist yet -- it's created downstream by the SSO federation when the user first authenticates.

When a service later reports metrics with `(external_id, email)`, the system must reconcile this with the operator-created account rather than creating a duplicate.

## Uniqueness Constraints

Two conditional unique constraints enforce identity integrity:

```
UNIQUE(external_id, type, organization) WHERE external_id != ''
UNIQUE(email, type, organization)       WHERE email != ''
```

This allows:
- Multiple accounts with blank `external_id` (different emails) -- operators can create many accounts before `external_id` is known
- Multiple accounts with blank `email` (different `external_id`s) -- services can report accounts without email
- Same email across different account types (e.g. a `user` and a `mailbox` for `alice@org.fr`)

This prevents:
- Two accounts with the same non-blank `external_id` + type + org
- Two accounts with the same non-blank `email` + type + org

## Account Lookup: `find_by_identifiers`

The `Account.find_by_identifiers()` classmethod provides a unified lookup with email fallback:

```python
account = Account.find_by_identifiers(
    organization=org,
    account_type="user",
    external_id="oidc-sub-123",
    email="alice@org.fr",
    reconcile_external_id=False,  # default
)
```

Lookup order:
1. Try `external_id` match (exact, scoped to type + org)
2. If no match, try `email` match (exact, scoped to type + org)
3. Return the found account or `None`

### Trusted External ID Backfill

When `reconcile_external_id=True` and the account was found by email (not by `external_id`), the method backfills the `external_id` **only if the account doesn't already have one**:

```python
# Trusted service can bind external_id to email-matched account
account = Account.find_by_identifiers(
    organization=org,
    account_type="user",
    external_id="oidc-sub-123",
    email="alice@org.fr",
    reconcile_external_id=True,
)
# If found by email and external_id was blank, it's now set to "oidc-sub-123"
```

An existing `external_id` is never overwritten, even by trusted sources.

## Security: Trust Boundaries

By default, services are **not trusted** to establish the `external_id <-> email` binding.

### Why this matters

A buggy or compromised service could report `external_id="ATTACKER-SUB", email="alice@org.fr"`. If the system blindly backfilled `external_id`, the attacker's OIDC subject would be permanently bound to Alice's account. When the attacker later authenticates via SSO with their own `sub`, they would inherit Alice's roles and entitlements -- a privilege escalation.

### Trusted service flag

Services under direct operator control can be flagged as trusted in their configuration:

```json
{
  "trusted_account_binding": true
}
```

Only trusted services trigger `reconcile_external_id=True` during metrics scraping. Untrusted services can still use email fallback for read-only metric association but cannot modify any account fields.

## Usage in Metrics Scraping

When `store_service_metrics()` processes incoming metrics with account data:

1. **Account with `external_id` found** -- update email if changed (safe: the service knows the identity)
2. **Account found by email fallback + trusted service** -- backfill `external_id`
3. **Account found by email fallback + untrusted service** -- associate metric to account, don't touch `external_id`
4. **No account found** -- create a new account with the provided identifiers

## Usage in Entitlements Resolution

The `get_context_account()` function in the entitlements resolver uses `find_by_identifiers` to look up accounts for entitlement checks. This means entitlement requests that provide either `account_id` (external_id) or `account_email` will find the correct account regardless of which identifier was set first.

## Typical Lifecycle

```
1. Operator creates account:
   Account(email="alice@org.fr", external_id="", type="user", org=Mairie)

2. Operator sets entitlements for alice@org.fr

3. Alice logs into a service via SSO, gets OIDC sub "abc-123"

4. Service reports metrics: {account: {id: "abc-123", email: "alice@org.fr"}}

5. Metrics scraping calls find_by_identifiers:
   - external_id="abc-123" -> no match
   - email="alice@org.fr"  -> match!
   - If trusted service:   backfill external_id="abc-123"
   - Associate metric to alice's account

6. Next scrape: external_id="abc-123" -> direct match (fast path)
```
