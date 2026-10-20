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
published in the generated allowlist as a `source: routed` row (it is live), and matches on both
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

`candidates` is rebuilt for every commune by `proconnect_regen_candidate_domains`,
which the `import_dpnt_dataset` task (daily, `cron.json`) runs as its last step. A
commune that already has DILA domains of its own still gets candidates (alternate
spellings, other extensions), minus its own DILA domains. It
runs after the `dpnt` buckets are up to date because a candidate is dropped when
another organization has the domain in `dpnt` or `manual`, or routes it. Between two
imports, a domain that becomes live or is added to `manual` stays in other
organizations' `candidates` until the next one; run the command by hand to refresh
sooner.

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
  (`allowed_attached_email_domains`, one entry per uid). It is a superset of
  everything we may ever push.

  Each domain is a mapping, not a bare string, with a `source`:

  ```yaml
  - domain: a.fr
    fiche: https://lannuaire.service-public.gouv.fr/bretagne/morbihan/<uuid>
    siret: "21560123400017"
    source: dila
  - domain: b.fr
    fiche: https://lannuaire.service-public.gouv.fr/bretagne/morbihan/<uuid>
    siret: "21560123400025"
    source: candidate
  - domain: c.fr
    fiche: https://lannuaire.service-public.gouv.fr/bretagne/morbihan/<uuid>
    siret: "21560123400033"
    source: routed
  ```

  - `routed`: the domain is already live, an active subscription sends it today.
    This is checked against the live subscriptions, not the buckets: a live domain
    that also sits in `dpnt`, `candidates` or `manual` is `routed`. api-partenaires
    checks every `dila` row against DILA and refuses the ones that fail, but accepts
    a `routed` row as is (with a warning), so a live domain must never depend on
    that check.
  - `dila`: not live, in the `dpnt` bucket (declared on service-public.gouv.fr). A
    `dila` row must have a `fiche`.
  - `manual`: not live, added by a superuser (the `manual` bucket).
  - `candidate`: not live, generated from the collectivité's name (the
    `candidates` bucket). A `dpnt` domain whose organization has no valid fiche
    ends up here too, or in `routed` if it is live.

  The best applicable source wins, in the order `routed`, `dila`, `manual`,
  `candidate`.

  A domain is looked up across all organizations, not only those scoped to the
  provider being written:

  - a `manual` or `candidate` row is not written for a provider when the domain is
    live on another provider (it would be refused as taken). A `dila` row is kept on
    every provider whose scope holds the organization;
  - a `candidate` row is not written when another organization has the domain in
    `dpnt`, which is how a homonym's guess stops overwriting a `dila` row. A
    `manual` row is kept: a superuser chose it.

  - `siret` is the organization's SIRET, on every row that has a valid one (14
    digits). It is quoted: bare, 14 digits are a YAML integer.
  - `fiche` is the organization's Service-Public URL, on every row whose
    organization is a commune, an EPCI, a département or a région. It must look
    like a fiche (`https://lannuaire.service-public.gouv.fr/.../<uuid>`).

  Their schema (`src/oidc_providers_config.ts` in api-partenaires) currently knows
  `dila` and `routed` only (`candidate` was removed in #90 and `manual` renamed to
  `routed` in #80), so the file we generate is not accepted by it as is. The renderer refuses to write an
  unknown source, a `dila` row without a valid fiche, or a fiche or SIRET with an
  invalid shape: this file gates authentication, and these values are imported data.

  Always gated: `Authorization: Bearer <PROCONNECT_ALLOWLIST_VIEW_API_KEY>`, and
  an unset key closes the route rather than opening it — same rule as every other
  static-key route, so forgetting to configure one can never publish it. Built on
  every request, so what you fetch is always current.
- The **deployed** allowlist is theirs: the same file, in their repo, updated by PR.
  It lags ours, and their API rejects any domain not yet in it.

`proconnect_fetch_prevalidated` fetches the deployed one hourly (`cron.json`) and
caches it per idp (it only reads the `domain` of each row: `source`, `fiche` and
`siret` are ignored, and a provider whose rows yield no readable domain keeps its
previous cache entry), so `proconnect_prevalidated` can tell the user which domains are
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
field lands in `dpnt`, becomes routable, and is published as a `source: dila` row
with the organization's fiche.

That is how the first PR ended up proposing `intramuros.org` (declared by 249
organizations), `lapagelocale.fr` (102), `facebook.com` (49), `espace-citoyens.net`
(29), `sites.google.com` (27) and `padlet.com`, plus 75 names under `wixsite.com`,
59 under `e-monsite.com`, 56 under `jimdofree.com`, 50 under `free.fr`, 39 under
`wordpress.com` and 21 under `blogspot.com`. None of these belong to a
collectivité, and a commune whose website is a Wix page has no mailbox on
`wixsite.com` to route.

**3. `claimed_domains()`, for candidates.** Candidate domains are guesses derived
from the commune's name, and the only filter on them is that another *collectivité*
does not provably own the name (in `dpnt` or `manual`, or live). That filter cannot see a domain owned by anyone
else, so the generator proposed `ens.fr` to the commune of Ens (65), `vogue.fr` to
Vogüé (07), `lancome.fr` to Lancôme (41), `lapeyre.fr` to Lapeyre (65) and
`lamontagne.fr` to La Montagne (70). It also proposed the same name to two or three
homonymous communes 1 689 times.

Nor does it ask whether the name exists: 94 % of the candidates in the first PR
(128 785 of 137 208 `.fr` names) are not registered. Pre-authorizing an unregistered
name hands the routing to whoever registers it first, for the price of a domain.

**4. The review script.** `scripts/validate_proconnect_allowlist.py` runs on the
api-partenaires PR and puts every domain of the new file into exactly one of six
categories, tried in order, so the counts always add up to the size of the file.
It reads the `domain`, `source` and `fiche` fields of each entry, and flags any line
it does not recognise rather than skipping it. Its own docstring is the reference;
the short version is:

| | |
|---|---|
| `not_allowed` | on the deny list in the script, or under a domain that is. An error whatever else is true, which is why it is tested first: `orange.fr` is a perfect reconstruction of the name of the commune of Orange, and `vogue.fr` of Vogüé. |
| `reconstructible` | the suggest rules could have built it from the collectivité's name. A guess, not evidence. |
| `previous_allowlist` | already deployed, so this PR is not granting it. |
| `dila_ok` | declared on service-public.gouv.fr by *exactly one* collectivité, the name carries the collectivité's (RPNT 2.2) and is not internationalized (RPNT 1.2). Neither the extension nor 2.3 (site and mail on the same domain) is checked. |
| `dila_not_reconstructible` | declared by *exactly one* collectivité like `dila_ok`, but the name does not carry the collectivité's (an acronym, a neighbouring place). Allowed all the same: the single declaration is the evidence. |
| `to_be_validated` | everything else: shared or undeclared domains, and internationalized names. A human decides. |

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

Any change to an active ProConnect subscription's domains syncs the provider
synchronously, inside the request's transaction (`core/signals.py` →
`sync_proconnect_provider`), so a failed sync rolls the change back instead of
drifting. A provider is the `idp_id` of the **service**: operators cannot override
it (`OperatorServiceConfig` refuses the key, and ignores one saved before that rule).
Reassigning a subscription's **service** syncs too, and syncs *both* providers: the
subscription moves provider with its domains untouched, so the one it left has to be
recomputed as well. Bulk writes bypass signals: reconcile with
`manage.py proconnect_sync`.

A sync reads the provider's live domains, then makes one call per difference, on
api-partenaires' per-domain routes: `DELETE` for each domain we no longer route
(first, so a domain moving between providers is free in time), `PUT` for each one
the provider lacks. Nothing is sent as a whole list. What follows from that:

- **Rate limit.** api-partenaires allows, by default, 10 requests a minute per
  provider (60 overall), and a sync costs one read plus one call per domain. A web
  request only waits out a `Retry-After` of 10 seconds, so a change that touches
  about ten domains fails with a 502 and is rolled back. The batch commands wait
  out a whole window (65 seconds), so a large backfill takes about a minute per ten
  domains and provider, while holding that provider's lock.
- **Refused domains.** A domain api-partenaires refuses (not allowed, taken,
  unreachable) does not stop the others. In a request the calls already made are
  then undone, best effort, and the user is told which domains were refused, with
  the same messages as before. The batch commands keep what went through and report
  the failure.
- **Not atomic.** Any other error (a 5xx, a rate limit that lasts) stops the sync
  where it is. If undoing fails too, the provider is left with part of the change:
  the next sync converges it, being computed from the live state, and the drift
  check flags it meanwhile.

### Drift detection and the `out_of_sync` flag

`manage.py proconnect_detect_drift` compares what each provider serves with what we
intend to route, and exits non-zero on any difference. It runs every hour, right
after `proconnect_fetch_prevalidated`, in the same `cron.json` job (a failed fetch
does not skip it).

It also maintains `Service.config["out_of_sync"]` (read as `Service.out_of_sync`):

- **Set** when the service's provider drifted. A provider that looks drifted is
  checked again under its push lock first, so a request that pushed but has not
  committed yet is not read as drift.
- **Effect.** The API refuses PATCH (which also creates a subscription) and DELETE
  on a subscription of that service (409, `ProConnectOutOfSync`), and the interface
  disables the switch and the domain editor. Editing an organization's
  `proconnect_domains` buckets is not blocked: they are an inventory, not what is
  pushed.
- **Cleared** by the next run that reads the provider and finds it in sync, or at
  once by saving the subscription's *ProConnect manual actions* page in the admin,
  which pushes the database state to ProConnect and rechecks it. With *Skip the
  ProConnect push* ticked nothing is pushed: the provider is still rechecked, so the
  flag only clears if it already matches.
- An unreadable provider changes nothing: no reading is no evidence.
- Providers of flagged services are rechecked even without an active subscription,
  otherwise nothing could ever clear their flag.

Every other push rechecks the provider too, so the flag follows the push instead of
waiting for the next hourly run:

- `proconnect_sync` and `subscribe_bulk` recheck each provider they pushed, failed
  pushes included (a failed push leaves the provider drifted, which sets the flag).
  `proconnect_sync --dry-run` pushes nothing and rechecks nothing.
- A subscription saved or deleted through the signals (the standard admin form, for
  instance) rechecks the providers it pushed, after the commit, only when one of
  them is flagged.

Pushes are serialized per provider by an advisory lock, and each routed domain is
locked before the uniqueness check, so two subscriptions cannot both claim it.

## Not the domains service

`Organization.proconnect_domains` and the **domains** service
([docs/domains.md](domains.md)) both hold domain names and have nothing else in
common: the domains service is about what serves a domain's *website*, and nothing
declared there reaches ProConnect. What both share is the shape of a domain name —
`core/services/domainnames.py`, one validator and one normal form.
