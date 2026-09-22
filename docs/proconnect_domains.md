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

`proconnect_fetch_prevalidated` fetches the deployed one hourly (the worker's
scheduler, see [deployment.md](deployment.md#background-tasks)) and
caches it per idp, so `proconnect_prevalidated` can tell the user which domains are
routable *now* ("pré-validé") and which are waiting for the next deploy ("pas
encore pré-validé", up to a week). The cache TTL
(`PROCONNECT_DOMAIN_ALLOWLIST_CACHE_TTL`, 4h) is the fallback if the schedule
stops,
not the refresh rate. Null means we do not know that provider's allowlist — shown
as unknown, never as "not pre-validated".

The ProConnect card also **blocks activation** while a domain it would route is
known to be absent from the deployed allowlist, since the push would be rejected
and rolled back. That verdict comes from the cache above, so it lags it by up to an
hour: right after an allowlist PR lands, run `proconnect_fetch_prevalidated` rather
than waiting for the next tick.

## What keeps `wanadoo.fr` out of the allowlist, and what does not

Routing a domain to a provider says "everyone at this domain authenticates as this
collectivité". So the question ProConnect asks about any allowlist entry is not
"does this domain exist" but "does this one organization own it". Today the answer
comes from four layers, and only the last of them is a real check.

**1. RPNT 2.2, on the email side only.** The `dpnt` bucket takes the org's email
domain when criteria 2.1 *and* 2.2 hold, and [2.2](https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#2.2)
is precisely "the address must not use a generic domain". That is the layer that
keeps `wanadoo.fr` and `orange.fr` out, and it works: they are the top two domains
in the whole DILA directory, declared by 10 800 and 8 601 distinct SIREN.

It is a hand-maintained list of 50 names, though (`GENERIC_EMAIL_DOMAINS` in
[st-home](https://github.com/suitenumerique/st-home/blob/main/data/tasks/defs.py)),
so it holds exactly the names somebody thought to type. `gmail.com` is on it,
`gmail.fr` is not, and `gmail.fr` reached the first api-partenaires PR. So did
`aol.com`, `mailo.com`, `online.fr` and `9online.fr`.

**2. Nothing at all, on the website side.** `rpnt_valid_site_domain` requires
criterion 1.1 only ("a website is declared on service-public.gouv.fr"). 2.2 is a
*mail* criterion and never applies to the website domain, and 1.2 (sovereign
extension) is not required either. Whatever a commune wrote in its `site_internet`
field lands in `dpnt`, becomes routable, and is published as `# Source: DILA`.

That is how the first PR ended up proposing `intramuros.org` (declared by 249
organizations), `lapagelocale.fr` (102), `facebook.com` (49), `espace-citoyens.net`
(29), `sites.google.com` (27) and `padlet.com`, plus 75 names under `wixsite.com`,
59 under `e-monsite.com`, 56 under `jimdofree.com`, 50 under `free.fr`, 39 under
`wordpress.com` and 21 under `blogspot.com`. None of these belong to a
collectivité, and a commune whose website is a Wix page has no mailbox on
`wixsite.com` to route.

**3. `claimed_domains()`, for candidates.** Candidate domains are guesses derived
from the commune's name, and the only filter on them is that another *collectivité*
does not provably own the name. That filter cannot see a domain owned by anyone
else, so the generator proposed `ens.fr` to the commune of Ens (65), `vogue.fr` to
Vogüé (07), `lancome.fr` to Lancôme (41), `lapeyre.fr` to Lapeyre (65) and
`lamontagne.fr` to La Montagne (70). It also proposed the same name to two or three
homonymous communes 1 689 times.

Nor does it ask whether the name exists: 94 % of the candidates in the first PR
(128 785 of 137 208 `.fr` names) are not registered. Pre-authorizing an unregistered
name hands the routing to whoever registers it first, for the price of a domain.

**4. The review script.** `scripts/validate_proconnect_allowlist.py` runs on the
api-partenaires PR and puts every domain of the new file into exactly one of five
categories, tried in order, so the counts always add up to the size of the file.
Its own docstring is the reference; the short version is:

| | |
|---|---|
| `not_allowed` | on the deny list in the script, or under a domain that is. An error whatever else is true, which is why it is tested first: `orange.fr` is a perfect reconstruction of the name of the commune of Orange, and `vogue.fr` of Vogüé. |
| `reconstructible` | the suggest rules could have built it from the collectivité's name. A guess, not evidence. |
| `previous_allowlist` | already deployed, so this PR is not granting it. |
| `dila_ok` | declared on service-public.gouv.fr by *exactly one* collectivité, and that declaration passes RPNT 1.2, 2.2 and 2.3. |
| `to_be_validated` | everything else. A human decides. |

The deny list is hand-maintained, and deliberately narrower than st-home's
`GENERIC_EMAIL_DOMAINS`: that one also holds mutualised *public* domains, which are
not one commune's own but are not an error either (`selonnet.fr` is on it, and is
the official site of the commune of Selonnet). What replaces the list for
everything else is the "exactly one collectivité" test in `dila_ok`, which needs
nothing maintained: `facebook.com` is declared by 49 collectivités,
`intramuros.org` by 249, `wanadoo.fr` by 10 800, while `abbeville.fr` is declared
by one.

The gap this leaves is that layer 4 runs on *their* side, at review time, on a PR
built from data layers 1 to 3 already let through. Closing it here means teaching
the generator the same rules: apply the deny list and the "exactly one
collectivité" test to the website domain as well as the email one.

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

**Neither is scheduled.** `proconnect_fetch_prevalidated` is the only ProConnect
job on the worker's schedule, so both reconciliation commands are manual today —
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
