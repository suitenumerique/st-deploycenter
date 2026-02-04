# Account Roles & Admin Entitlement Resolution

## Overview

The deploy center uses a layered role system to determine whether an account has admin privileges on a given service. Roles can be assigned at multiple levels, and different services may extend the base resolution logic.

## Role Levels

The following 2 levels can be set in the frontend, in each Organization page "Roles" tab.

### Organization-level roles (`Account.roles`)

Each account has a `roles` JSON array (e.g. `["admin"]`, `["member"]`). These are organization-wide roles that apply across all services.

### Service-level roles (`AccountServiceLink.roles`)

An account can have per-service roles via `AccountServiceLink`. These allow finer-grained control (e.g. admin on one service but not another).

## Admin Entitlement Resolution

When a service calls the entitlements API, the system resolves whether the account is an admin. The resolution follows a chain of checks that stops at the first match.

### Default `AdminEntitlementResolver`

Used by most service types. Checks:

1. **Organization role**: `"admin"` in `account.roles` -> `is_admin: True`, level: `"organization"`
2. **Service-link role**: `"admin"` in the account's service link roles -> `is_admin: True`, level: `"service"`
3. If neither matches -> `is_admin: False`

### `ExtendedAdminEntitlementResolver` (ADC/ESD services)

Used by `adc` and `esd` service types. Extends the default resolver with three additional resolution levels:

1. **Explicit role** (inherited from base): Organization or service-link admin role -> `is_admin: True`
2. **Email contact**: Account email matches the organization's `adresse_messagerie` -> `is_admin: True`, level: `"email_contact"`
3. **Auto-admin metadata**: Explicit operator choice stored in `subscription.metadata["auto_admin"]`:
   - `"all"` -> `is_admin: True`, level: `"auto_admin"` (bypasses population check)
   - `"manual"` -> `is_admin: False` (bypasses population check)
4. **Population fallback** (only if no `auto_admin` choice): Organization population under threshold -> `is_admin: True`, level: `"population"`

### Resolution priority order

```
explicit role > email contact > auto_admin metadata > population fallback
```

When `auto_admin` is explicitly set (either value), the population check is bypassed entirely. The population check only runs as the default when no choice has been made yet.

## Auto-Admin Configuration

### Service-level threshold

The population threshold can be configured per service via `service.config["auto_admin_population_threshold"]`. Defaults to 3500.

### Subscription-level override (`auto_admin` metadata)

Operators can explicitly choose the admin mode for each organization-service subscription. This choice is stored in `subscription.metadata["auto_admin"]` and takes one of two values:

| Value | Effect |
|---|---|
| `"all"` | All accounts are granted admin (bypasses population check) |
| `"manual"` | Only accounts with explicit admin roles or email contact match get admin (bypasses population check) |

### Frontend behavior

The frontend computes a **default** mode when no explicit choice has been persisted:
- If the organization's population is known and below the threshold -> default is `"all"`
- Otherwise -> default is `"manual"`

The service card displays:
- **"Defaut: Tous"** or **"Defaut: Specifiques"** when using the computed default
- **"Tous"** or **"Manuels"** when an explicit choice has been saved

When the operator saves a choice in the modal, it's persisted via `PATCH /subscription/` with `{ metadata: { auto_admin: "..." } }`. Existing metadata keys are preserved.

## Example Scenarios

### Small commune, no explicit choice
- Population: 500 (under threshold)
- No `auto_admin` in metadata
- Result: all users are admin (level: `"population"`)
- Card shows: "Defaut: Tous"

### Large commune, no explicit choice
- Population: 10000 (over threshold)
- No `auto_admin` in metadata
- Result: only explicit admins/email contacts get admin
- Card shows: "Defaut: Specifiques"

### Operator forces all-admin on large commune
- Population: 10000
- `auto_admin: "all"` in metadata
- Result: all users are admin (level: `"auto_admin"`)
- Card shows: "Tous"

### Operator restricts small commune
- Population: 500
- `auto_admin: "manual"` in metadata
- Result: only explicit admins/email contacts get admin
- Card shows: "Manuels"
