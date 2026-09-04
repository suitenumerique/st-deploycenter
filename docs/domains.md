# Domains service

## Overview

The **Domains** service lets an organization declare its own domain names and choose
what serves each one's website: a **parking page** we generate (the default), an
external server pointed at by a DNS `A` or `CNAME` record, or an **HTTP redirection**
(permanent 301 or temporary 302). It is a regular service: it shows up as a card on
the organization page, with an on/off subscription switch.

The domains are expected to be delegated to the ANCT nameservers
(`DOMAINS_NAMESERVERS`, `ns1.lst-domaines.fr` / `ns2.lst-domaines.fr` by default),
which is what the modal tells the user and what the check below compares against.

It is unrelated to the ProConnect card, which routes domains to an identity
provider ([docs/proconnect_domains.md](proconnect_domains.md)). Nothing declared
here reaches the ProConnect allowlist.

## Storage

Everything lives in the subscription metadata of the `domains` service
(`ServiceSubscription.metadata`), so there is no dedicated model:

```json
{
  "domains": ["exemple.fr", "ville-x.fr"],
  "website": {
    "exemple.fr": {"mode": "parking"},
    "ville-x.fr": {"mode": "dns_a", "target": "192.0.2.1"}
  }
}
```

`domains` is normalized on write (lowercased, deduped, sorted, valid fqdns only).
`website` holds exactly one entry per declared domain, with `mode` in:

| Mode | What serves the domain | `target` |
|---|---|---|
| `none` | nothing (not offered in the modal: it is where a domain we cannot park sits until it is pointed somewhere) | — |
| `parking` | a page we generate | — |
| `dns_a` | an external server, `A` / `AAAA` records | up to 10 IPv4/IPv6 addresses, comma-separated |
| `dns_cname` | an external server, DNS `CNAME` record | a domain name |
| `redirect_301` | a permanent HTTP redirection | an https url |
| `redirect_302` | a temporary HTTP redirection | an https url |

All the logic lives in `core/services/domains.py`.

Rules enforced on write (`ServiceSubscriptionSerializer._validate_domains_subscription`):

- a malformed domain is rejected (400) instead of being silently dropped;
- at most 100 domains per organization;
- a website entry must refer to a declared domain, use a known mode, and carry a
  valid target for the modes that need one (an IP is refused as a `CNAME` target);
- `dns_a` takes IPv4 and IPv6 in the same field, comma-separated: the record type
  follows from the address family, so there is nothing for the user to pick. Each
  address is stripped of surrounding whitespace and stored in canonical form
  (IPv6 compressed and lowercased), deduped, in the order given; one bad address
  fails the whole field rather than being dropped;
- a redirection target is normalized to an https url: `http` is upgraded, a bare
  `exemple.fr/page` is read as a url, and a url with credentials or an IP host is
  refused;
- `parking` requires an RPNT 1.2 conformant extension (see below); a domain not
  mentioned defaults to `{"mode": "parking"}` when it has one, `{"mode": "none"}`
  otherwise;
- while the subscription is active, its domains are exclusive: a domain already
  declared by another *active* domains subscription is refused, so a parking page
  never has two organizations behind it.

Any member of an operator managing the organization can declare domains and change
their website configuration (no superuser requirement).

## RPNT 1.2 and parking pages

RPNT [criterion 1.2](https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#1.2)
requires a collectivité's domain to use a sovereign extension —
`DOMAIN_EXTENSIONS_ALLOWED` in `core/services/domains.py` (`.fr`, the regional and
the overseas extensions), kept in sync with the list of the same name in
[st-home](https://github.com/suitenumerique/st-home/blob/main/data/tasks/defs.py),
which computes the `rpnt` criteria we import.

**Internationalized domains never qualify**, whichever way they are written: the
unicode `stmearddegurçon.fr` and the punycode `xn--stmearddeguron-rjb.fr` are the
same name, and `is_internationalized()` refuses both. The extension check alone would
accept them, since `xn--….fr` ends in `.fr`. A domain a citizen cannot type, read
back or tell apart from a lookalike is not an official address.

A collectivité's website is only served on a conformant domain — our parking page as
much as its own server. So `parking`, `dns_a` and `dns_cname` are refused on write
for anything else (`allowed_modes()` in `core/services/domains.py`), and an entry
stored with one of them on a non-conformant domain reads back — and exports — as
`none`. A non-conformant domain can still redirect to the official one
(`redirect_301` / `redirect_302`) or serve nothing.

The modal renders this from the `allowed_modes` the check returns: `parking` stays in
the dropdown but greyed, to show what the domain would get if it were conformant,
while the A/CNAME entries are dropped from the list entirely. Which of the two a
disallowed mode gets is the only part of the rule the frontend holds, and it is
presentation, not validation.

## Checking a domain's configuration

`POST /api/v1.0/operators/<operator_id>/organizations/<organization_id>/domains-check/`
answers, for each domain, whether it is delegated to our nameservers and whether it
is RPNT 1.2 conformant. The modal calls it when it opens and whenever the list
changes; the domains do not have to be declared yet.

```json
{"domains": ["exemple.fr", "exemple.com"]}
```

```json
{
  "expected_nameservers": ["ns1.lst-domaines.fr", "ns2.lst-domaines.fr"],
  "results": [
    {
      "domain": "exemple.fr",
      "nameservers": ["ns1.lst-domaines.fr", "ns2.lst-domaines.fr"],
      "nameservers_valid": true,
      "error": null,
      "rpnt_1_2_valid": true,
      "extension": "fr"
    },
    {
      "domain": "exemple.com",
      "nameservers": [],
      "nameservers_valid": false,
      "error": "nxdomain",
      "rpnt_1_2_valid": false,
      "extension": "com"
    }
  ]
}
```

Each result also carries `allowed_modes` and `default_mode` for the domain, and the
payload carries `modes_with_target` — so the modal builds its website dropdown from
the backend's rules instead of restating them. The only validation left in the
browser is a domain-shaped regex on the "add a domain" box; every mode and every
target is checked server-side, on save, and the serializer's message is what the user
sees.

- `nameservers_valid` demands the exact expected set: an extra nameserver means part
  of the zone is served elsewhere, which is a misconfiguration too.
- `error` is `nxdomain`, `not_delegated`, `timeout` or `error` when the lookup
  produced no nameservers, and `null` otherwise.
- A domain that is not a well-formed fqdn is dropped from the results rather than
  rejected: the modal checks the list as the user typed it.
- Access is the usual operator/organization one — no API key.

The lookups (`core/services/dns.py`) use
[recursive-resolver](https://pypi.org/project/recursive-resolver/): an iterative walk
from the DNS root, so we read what the authoritative servers publish rather than what
a shared cache remembers. Only the root → TLD delegations are cached
(`max_delegation_cache_depth="tld"`), so a delegation the user just changed at their
registrar shows up on the next check while the root servers are left alone. Domains
are resolved concurrently and the batch has a wall-clock deadline
(`dns.BATCH_TIMEOUT`), past which the remaining domains are reported as timed out.

The timeouts are strictly nested — per query (5s) < per name
(`DOMAINS_DNS_MAX_RESOLUTION_TIME`, 15s) < batch (`dns.BATCH_TIMEOUT`, 20s) < the 25s
a request has to stay under, because the platform router closes the connection at
30s. Each budget fails inside the next, so a slow domain produces our own
"vérification impossible" rather than a platform error, and a lookup is never cut off
while still inside its own budget. Raise one and check the others still hold.

## Reading the domains from an external job

`GET /api/v1.0/domains/` returns every domain of every **active** domains
subscription, with the organization data a parking page needs:

```
curl -H "Authorization: Bearer $DOMAINS_API_KEY" \
     "https://<host>/api/v1.0/domains/"
```

```json
{
  "count": 1,
  "results": [
    {
      "domain": "ville-x.fr",
      "website": {"mode": "parking"},
      "records": [],
      "updated_at": "2026-08-14T12:00:00Z",
      "organization": {
        "id": "…", "name": "Ville X", "type": "commune",
        "siret": "…", "siren": "…", "code_insee": "…", "code_postal": "…",
        "population": 2500, "departement_code_insee": "…", "region_code_insee": "…",
        "adresse_messagerie": "mairie@ville-x.fr", "telephone": "…",
        "site_internet": "…", "service_public_url": "…"
      },
      "operator": {"id": "…", "name": "Opérateur"}
    }
  ]
}
```

Two fields describe the domain, and they answer different questions:

- **`website`** — what **we** serve for it. Its `mode` is one of `parking`,
  `redirect_301`, `redirect_302` or `none`, with `target` (the https url) on the two
  redirections. The stored `dns_a` / `dns_cname` modes never appear here: a domain
  pointing at an external server is not something we serve, so it exports as
  `{"mode": "none"}` and says where it goes through `records`.
- **`records`** — the DNS records to publish for it, as
  `{"prefix", "type", "value"}`. `prefix` is the record's name relative to the
  domain, always `""` (the apex) for now. `type` is `A`, `AAAA` or `CNAME`; for the
  address mode it follows from each address's family, which is why the user is never
  asked to pick between `A` and `AAAA`. Empty for everything we serve ourselves.

So `{"mode": "none", "records": []}` means "nothing configured" and
`{"mode": "none", "records": [...]}` means "points elsewhere" — the distinction is on
the records, not on the mode.

- Every declared domain is returned, unfiltered: a job that only wants the parking
  pages keeps the entries whose `website.mode` is `parking`. There is no query
  parameter, and an unknown one is ignored rather than refused.
- The response is not paginated: one snapshot per run, one query. `count` is simply
  `len(results)` — despite the shape, there is no `next` page to follow.
- Access requires `Authorization: Bearer <key>` matching the `DOMAINS_API_KEY`
  setting. When that setting is empty the route is closed to everyone.
