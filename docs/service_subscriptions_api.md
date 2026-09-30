# Service subscriptions API

Lets a service manage the subscriptions to itself, for instance from a signup
form on the service side.

## The key

Each `Service` can have one subscriptions API key. None exists by default: a
staff member generates it from the service's page in the Django admin
("Generate subscriptions API key"). The key is shown once, in the confirmation
message. Only its SHA-256 is stored (`Service.subscriptions_api_key_hash`).
Generating again replaces the key, "Revoke subscriptions API key" removes it.

It is sent as `Authorization: Bearer <key>` and only works on the endpoints
below, for its own service (any other `service_id` answers 403). It is
unrelated to the service's `external_management_api_key` and
`entitlements_api_key`, which are not accepted here.

## Endpoints

All under `/api/v1.0/services/<service_id>/`.

| Method | Path | |
|---|---|---|
| `GET` | `subscriptions/` | The service's subscriptions. Filters: `siret`, `operator_id`, `is_active`. Paginated. |
| `POST` | `subscriptions/` | Create one. Body: `siret`, `operator_id`, `is_active` (required), `metadata` (optional). |
| `GET` | `subscriptions/<id>/` | One subscription. |
| `PATCH` | `subscriptions/<id>/` | Change `is_active`, `operator_id` and/or `metadata` (at least one). |
| `DELETE` | `subscriptions/<id>/` | Delete it. |
| `GET` | `operators/` | Active operators configured for the service (`OperatorServiceConfig`). With `?siret=`, only those managing that organization. Paginated. |

A subscription is returned as:

```json
{
  "id": "…",
  "organization": {"id": "…", "siret": "…", "name": "…", "type": "commune"},
  "operator": {"id": "…", "name": "…", "url": "…"},
  "is_active": true,
  "metadata": {},
  "created_at": "…",
  "updated_at": "…"
}
```

## Metadata

Only some metadata keys can be read and written with the key, per service type
(`SERVICE_KEY_METADATA_KEYS` in `core/api/viewsets/service_subscriptions.py`):

| Service type | Keys |
|---|---|
| `bal` | `epci_delegation` |

`metadata` in responses only holds those keys, and any other key sent is
refused (400). On PATCH, the keys sent are merged into the stored metadata;
the other keys are kept. Entitlements are neither exposed nor writable.

## Rules

- `operator_id`, on creation or PATCH, must be one of
  `operators/?siret=<siret>`: an active operator, configured for the service,
  with an `OperatorOrganizationRole` on the organization. Otherwise 400.
  Moving an active subscription to another operator also applies the
  activation rules with that operator's config.
- An organization has at most one subscription per service: creating a second
  one answers 409, whichever operator holds the first.
- Fields not listed above are refused (400), not ignored.
- Writes go through the same validation as the operator API
  (`ServiceSubscriptionSerializer`): activation rules (required services,
  population limits) and the service-specific metadata (ProConnect, domains).
  Webhooks and ProConnect pushes fire as for any other change.
