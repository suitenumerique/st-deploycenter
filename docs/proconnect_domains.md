# ProConnect domains

## The two questions

Every domain in the ProConnect card answers one of two questions, and keeping them
apart is most of what there is to understand:

| Question | Answer lives in | Read it with |
|---|---|---|
| **What may this organization route?** | `Organization.proconnect_domains` (the buckets) | `routable_domains(org)` |
| **What is actually routed to this provider?** | the ProConnect subscription's `metadata["domains"]` | `idp_routed_domains(idp_id)` |

The first is an inventory the collectivité and the superusers curate. The second is
the routing decision, per subscription, and it is exactly what we push to
api-partenaires.

The UI only ever offers the first when editing the second, but that is a
convention, not an enforced invariant: the write path
(`ServiceSubscriptionSerializer._validate_proconnect_subscription`) checks that a
superuser's domains are well-formed and claimed by no other active subscription —
it does **not** check them against `routable_domains()`. A routed domain also
counts as its own provenance, so one put there by mistake becomes routable, is
published in the generated allowlist as `# Source: routed`, and matches on both
sides of `proconnect_detect_drift`. Nothing downstream will flag it.

## The buckets

`Organization.proconnect_domains` is a JSON dict of five lists. They are not five of
a kind — three say **where a domain came from**, two say **how far it got**:

| Bucket | Kind | Meaning |
|---|---|---|
| `dpnt` | provenance | declared on service-public.gouv.fr (DILA). Authoritative. |
| `candidates` | provenance | generated from the collectivité's name. A guess. |
| `manual` | provenance | added by a superuser. |
| `requested` | status | asked for by an operator member, awaiting validation. |
| `discarded` | status | set aside by a superuser. A tombstone, not a provenance. |

Read and write them through `core/services/proconnect.py` only —
`update_proconnect_domains()` locks the row, normalizes, and enforces the invariant
that a DILA domain lives in `dpnt` and in no other *provenance* bucket: every write
strips it from `manual`, `requested` and `candidates`. `discarded` is deliberately
exempt, since a discard is a tombstone rather than a provenance — and one placed on
a DILA domain has no effect anyway (see the routable rule). The admin shows the
field read-only for the same reason.

## The routable rule

One function, `domain_provenances()`, decides what may be routed, and everything
else reads it — the allowlist build, the API payload, the modal:

- routable = live (`routed`) ∪ `candidates` ∪ `manual` ∪ `dpnt`;
- a discard hides a candidate or a manual domain;
- a discard never hides a DILA domain — service-public.gouv.fr is authoritative;
- a discard never hides a live one either — dropping a domain the provider is
  using would cut off its users;
- `requested` is never routable: it is a pending ask, not a decision.

`routable_domains(org)` is the sorted list of those, `known_domains(org)` is
everything we hold (all five buckets plus what is live) — i.e. every row the modal
displays, including the asks and the tombstones.

The API exposes both derived views on the organization payload, so the frontend
never restates the rule:

```json
{
  "proconnect_domains": {"dpnt": ["…"], "candidates": [], "manual": [], "requested": [], "discarded": []},
  "proconnect_routable": ["…"],
  "proconnect_prevalidated": {"<idp_id>": ["…"]}
}
```

## Two allowlists, and why a domain can be routable but not routed yet

- The **generated** allowlist is ours: `GET /api/v1.0/proconnect/oidc_providers.yaml`
  renders every provider's routable domains as the YAML api-partenaires reads
  (`allowed_attached_email_domains`, one entry per uid, each domain commented with
  its provenance and the org's Service-Public URL). It is a superset of everything
  we may ever push.

  Always gated: `Authorization: Bearer <PROCONNECT_ALLOWLIST_VIEW_API_KEY>`, and
  an unset key closes the route rather than opening it — same rule as every other
  static-key route, so forgetting to configure one can never publish it. Built on
  every request, so what you fetch is always current.
- The **deployed** allowlist is theirs: the same file, in their repo, updated by PR.
  It lags ours, and their API rejects any domain not yet in it.

`proconnect_fetch_prevalidated` fetches the deployed one hourly (`cron.json`) and
caches it per idp, so `proconnect_prevalidated` can tell the user which domains are
routable *now* ("pré-validé") and which are waiting for the next deploy ("pas
encore pré-validé", up to a week). The cache TTL
(`PROCONNECT_DOMAIN_ALLOWLIST_CACHE_TTL`, 4h) is the fallback if the cron stops,
not the refresh rate. Null means we do not know that provider's allowlist — shown
as unknown, never as "not pre-validated".

The ProConnect card also **blocks activation** while a domain it would route is
known to be absent from the deployed allowlist, since the push would be rejected
and rolled back. That verdict comes from the cache above, so it lags it by up to an
hour: right after an allowlist PR lands, run `proconnect_fetch_prevalidated` rather
than waiting for the next tick.

## Pushing

Any change to an active ProConnect subscription's domains pushes the provider's full
list synchronously, inside the request's transaction (`core/signals.py` →
`sync_proconnect_provider`), so a failed push rolls the change back instead of
drifting. Reassigning a subscription's **operator** pushes too, and pushes *both*
providers: the effective `idp_id` is resolved per operator, so the subscription
moves provider with its domains untouched — the one it left has to be recomputed as
well. Bulk writes bypass signals: reconcile with `manage.py proconnect_sync`.
`manage.py proconnect_detect_drift` compares what each provider serves with what we
intend and exits non-zero on any difference.

**Neither is scheduled.** `cron.json` runs `proconnect_fetch_prevalidated` and
nothing else for ProConnect, so both reconciliation commands are manual today —
even though several code paths (`_sync_proconnect`'s docstring,
`_create_service_subscriptions` in `core/tasks/dpnt.py`) describe them as the net
that catches what the synchronous push cannot. Until one of them runs on a
schedule, drift from a bulk write is caught only when someone thinks to look.

Pushes are serialized per provider by an advisory lock, and each routed domain is
locked before the uniqueness check, so two subscriptions cannot both claim it.

## Not the domains service

`Organization.proconnect_domains` and the **domains** service
([docs/domains.md](domains.md)) both hold domain names and have nothing else in
common: the domains service is about what serves a domain's *website*, and nothing
declared there reaches ProConnect. What both share is the shape of a domain name —
`core/services/domainnames.py`, one validator and one normal form.
