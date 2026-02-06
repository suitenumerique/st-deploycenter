# Operator Auto-Join Configuration

## Overview

The `auto_join` feature allows operators to automatically onboard organizations during the DPNT import. When configured, the system creates `OperatorOrganizationRole` and `ServiceSubscription` records for matching organizations.

## Configuration

Add an `auto_join` key to the operator's `config` JSON field:

```json
{
  "auto_join": {
    "types": ["commune", "epci"],
    "services": [3, 7]
  }
}
```

| Key | Type | Description |
|-----|------|-------------|
| `types` | `string[]` | Organization types to match (e.g., `"commune"`, `"epci"`, `"departement"`, `"region"`) |
| `services` | `int[]` | Service IDs (`Service.id`) to create subscriptions for |

## Behavior

During each DPNT import (`import_dpnt_dataset` task), the `_process_auto_join()` function:

1. Queries all active operators with `auto_join` in their config
2. For each operator:
   - Validates that each service ID has a corresponding `OperatorServiceConfig` (logs a warning and skips services without one)
   - Finds all organizations matching the configured types
   - Bulk-creates `OperatorOrganizationRole` records (operator manages the org)
   - Bulk-creates active `ServiceSubscription` records for each valid service

## Key Characteristics

- **Idempotent**: Uses `ignore_conflicts=True` so re-runs don't create duplicates
- **Covers all matching orgs**: Processes all organizations in the database matching the type filter, not just newly imported ones
- **Non-destructive**: Does not modify or re-activate existing subscriptions that were manually deactivated
- **Requires OperatorServiceConfig**: Services referenced in `auto_join.services` must have a corresponding `OperatorServiceConfig` for the operator, otherwise they're skipped with a warning

## Security

The `auto_join` config is **not exposed through the REST API**. The `OperatorSerializer.get_config()` method whitelists only specific keys (e.g., `"idps"`), so `auto_join` remains internal.

## Import Statistics

The DPNT import returns statistics including:

```python
{
    "auto_join": {
        "operator_organization_roles_created": 150,
        "service_subscriptions_created": 300
    }
}
```

## Example

```python
# Operator config
operator.config = {
    "auto_join": {
        "types": ["commune"],
        "services": [1, 2]
    }
}

# After DPNT import, all communes will have:
# - OperatorOrganizationRole linking them to this operator
# - ServiceSubscription for services 1 and 2 (if OperatorServiceConfig exists)
```
