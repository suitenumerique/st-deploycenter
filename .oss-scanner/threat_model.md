# Threat model

## What this project does and where untrusted input enters

Deploy Center is a back office for operators of La Suite territoriale, a
French government platform (ANCT). An operator uses it to subscribe
organizations (communes, EPCI, départements...) to services. The operator
also manages accounts and roles there. The federated services read their
entitlements from it.

The backend is Django 5.2 with Django REST Framework, in `src/backend`. The
frontend is a Next.js static export in `src/frontend`, a client of the API
with no server rendering. Caddy sits in front
(`src/frontend/caddy/Caddyfile`).

Actors: anonymous Internet users; organization accounts (end users of the
federated services, they never log into Deploy Center); operator users (an
OIDC session through ProConnect, with optional multi-factor authentication,
`docs/authentication.md`); superusers (the Django admin, with a staff
session); external API clients (federated services and operator integrations
that authenticate with API keys).

Entry points:

- The REST API under `/api/v1.0/` (`src/backend/core/urls.py`, viewsets in
  `src/backend/core/api/viewsets/`).
- Public, no authentication: `lagaufre/`, `servicelogo/<id>/` (a stored SVG
  logo served inline), `config/`, and the OIDC views in
  `src/backend/core/authentication/views.py`.
- Behind a static API key (`src/backend/core/api/permissions.py`):
  `domains/`, `metrics/subscriptions-by-service/`,
  `proconnect/oidc_providers.yaml`.
- Behind a per-record API key sent as `Authorization: Bearer`:
  `Operator.external_management_api_key` and
  `Service.external_management_api_key`
  (`src/backend/core/authentication/__init__.py`).
- Behind `Service.config["entitlements_api_key"]`, sent as `X-Service-Auth`
  (`src/backend/core/api/permissions.py`): the `entitlements/` endpoint.
- `entitlements/`: the endpoint that decides the permissions of every
  federated service. The caller supplies `account_email` or `account_id`
  (`core/api/viewsets/entitlements.py`, `core/entitlements/resolvers/`).
- OIDC login through `mozilla-django-oidc`
  (`core/authentication/backends.py`, `middleware.py`).
- Outbound requests with an attacker-influenced target or answer:
  operator-configured webhooks (`core/webhooks.py`), the DNS delegation
  check with an iterative resolver (`core/services/dns.py`), metrics
  scraping of service endpoints (`core/tasks/metrics.py`), the ProConnect
  partner API push (`core/services/proconnect.py`), data.gouv imports
  (`core/tasks/dpnt.py`), and data.gouv exports (`core/tasks/datagouv.py`).
- The Django admin (`core/admin.py`), including SVG logo upload.
- The frontend SPA (`src/frontend/src`).

## Components that matter most / least

Most important, report findings here first:

- `core/api/permissions.py` and `core/authentication/` decide who can call
  an endpoint.
- `core/entitlements/resolvers/` decides who is an admin for a service.
- `core/api/viewsets/` enforces object-level permissions and queryset
  filtering per operator and organization.
- `core/models.py`, in particular `Account.find_by_identifiers` and the
  trust boundary in `docs/accounts.md`, "Security: Trust Boundaries".
- `core/webhooks.py` and `core/services/dns.py` send outbound requests with
  an attacker-influenced target.
- `core/services/proconnect.py` and `core/api/viewsets/proconnect.py` push
  an allowlist to the national SSO.
- Raw SQL in a `.raw()` or `.extra()` call, for example in
  `core/api/viewsets/organization.py`.

Less important, but still in scope: the importers in `core/tasks/` (trusted
government data sources), the metrics models, the management commands.

Out of scope, do not report findings here: `core/migrations/` (schema
history); `core/tests/` and `core/factories.py`; `src/keycloak/` (the
development OIDC realm); `env.d/`, `compose.yaml`, `Makefile`, `bin/`,
`scripts/`, `.opencode/`; `docs/assets`; third-party code in `/venv` and
`node_modules`; the frontend's dependency tree, because the export is
static.

## How to exercise it

The image for this scan places the backend at `/src/src/backend` and the
frontend at `/src/src/frontend`. `PYTHONPATH` and `PATH` are already set, and
`DJANGO_CONFIGURATION=Test` is already set.

PostgreSQL 17 runs in the image. Every bash shell starts it. Run
`pgctl start` yourself in a `sh` script. Use `pgctl start`,
`pgctl stop`, and `pgctl status` to control it, and `pgctl psql -d
deploycenter` to inspect the already migrated `deploycenter` database.

Run the backend tests:

```sh
cd /src/src/backend
pytest --reuse-db
```

Add `-n auto` to run the suite on all CPUs. Add `--create-db` after a model
change. Factories are in `core/factories.py`. Tests under `core/tests/api/`
show how to call each endpoint. Six tests start an HTTP server on a loopback
port and need a working loopback interface.

Run the development server:

```sh
cd /src/src/backend
python manage.py runserver 0.0.0.0:8000
```

Set `DJANGO_CONFIGURATION=DevelopmentMinimal` first for `DEBUG`. Static
files are already collected in `/data/static`. The swagger UI is at
`/api/v1.0/swagger/` under `Test`.

Run the frontend checks, all offline:

```sh
cd /src/src/frontend
npm run lint
npm run ts:check
npm run build
```

The frontend has no test suite. The static export lands in
`src/frontend/out`.

## How you rate severity

Critical: unauthenticated access to operator or organization data; an admin
entitlement granted to an account that must not have it (check every
resolver in `core/entitlements/resolvers/`, including `can_admin_operators`
and `can_admin_collectivites`); a forged or bypassed API key,
`X-Service-Auth` header, or OIDC authentication; account takeover through
the `external_id` binding in `docs/accounts.md`, "Security: Trust
Boundaries"; remote code execution; SQL injection, including after
authentication.

High: cross-operator or cross-organization read or write by an
authenticated operator user or API key (an IDOR); server-side request
forgery from an authenticated operator that reaches an internal service; a
leak of an API key or another secret; stored cross-site scripting in the
SPA or in a served SVG logo; cross-site request forgery on a state-changing
endpoint; a bypass of the multi-factor authentication requirement
(`docs/authentication.md`).

Medium: a leak of organization metadata or e-mail addresses with no
authorization; server-side request forgery limited to an operator's own
declared endpoints; a denial of service that one unauthenticated request
causes; a missing rate limit that lets an attacker enumerate accounts or
keys.

Low: an issue that needs a superuser session or the Django admin; a verbose
error message; an authenticated denial of service with no amplification.

Not a finding: anything that exists only under the `Test`, `Development`,
or `Build` settings classes in `src/backend/deploycenter/settings.py`;
reflected content in a JSON response, because the client is a static SPA.

## Anything to leave alone

- This image runs `DJANGO_CONFIGURATION=Test`, the same configuration CI
  uses: the MD5 password hasher, `USE_SWAGGER=True`, a dummy
  `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS=*`, a superuser database role
  named `user` with password `pass`, `fsync=off`, and fake
  `keycloak:8802` OIDC endpoints. Report against the `Production` class in
  `src/backend/deploycenter/settings.py`, not against `Test`.
- The image uses PostgreSQL 17. Development and CI use PostgreSQL 16.6
  (`compose.yaml`). This difference is intentional.
- Caddy can allowlist the Django admin by IP (`src/frontend/caddy/Caddyfile`),
  but only when `DEPLOYCENTER_ADMIN_IP_ALLOWLIST` is set. The default allows
  every address. The admin still needs a staff session.
- API keys are stored in plain text in the database. This is a known
  design choice. Report only an exposure of a stored key.
- SIRET codes, SIREN codes, and INSEE codes are public reference data.
- A dependency CVE with no reachable path in this code is not wanted.

## How reports and patches should look

Submit one finding per report, with a request that reproduces it: a `curl`
command against `runserver`, or a failing `pytest` test under
`core/tests` that uses the factories in `core/factories.py`.

Include a patch as a diff against `src/backend`. The patch must pass:

```sh
ruff check
ruff format --check
```

The project's line length is 88 characters (`src/backend/pyproject.toml`).

Send security questions outside this scan to security@suite.anct.gouv.fr,
per `SECURITY.md`.
