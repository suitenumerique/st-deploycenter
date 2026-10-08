# Environment variables

The backend reads its whole configuration from the environment, through
[django-configurations](https://django-configurations.readthedocs.io/) in
[`src/backend/deploycenter/settings.py`](../src/backend/deploycenter/settings.py).
This page lists every variable it reads. The variables of the web server
(Caddy) are in [`deployment.md`](deployment.md#web-server-environment-variables).

## Conventions

- **Names.** Settings declared with an explicit environment name use that name
  as-is (`REDIS_URL`, `OIDC_RP_CLIENT_ID`, ...). Settings declared without one
  are read from `DJANGO_<SETTING>` (`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
  ...). The tables give the real environment name in every case.
- **Lists** are comma-separated: `DJANGO_ALLOWED_HOSTS=example.org,www.example.org`.
  Spaces around the commas are ignored.
- **Booleans** accept `true`/`false`, `yes`/`no`, `on`/`off`, `1`/`0`
  (case-insensitive).
- **Dicts** are Python literals: `OIDC_AUTH_REQUEST_EXTRA_PARAMS={"acr_values": "eidas1"}`.
- **Unset vs empty.** A variable that is not set takes the default; one set to
  an empty string is an empty value (an empty list, `None` for a string), not
  the default.
- **Required** means the `Production` configuration cannot work without it.
  Development has its own defaults in
  [`env.d/development/backend.defaults`](../env.d/development/backend.defaults).

## Configuration selection

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DJANGO_CONFIGURATION` | `Development` | **yes: `Production`** | The settings class to load: `Production` for any deployment (`Feature`, `Staging` and `PreProduction` are aliases of it), `Development`, `DevelopmentMinimal` and `Test` for local work, `Build` while building the image. |
| `DJANGO_SETTINGS_MODULE` | `deploycenter.settings` | no | The settings module. Leave it alone. |

## Security

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DJANGO_SECRET_KEY` | _(none)_ | **yes** | Django's secret key: signs the session and CSRF cookies. Long and random; changing it logs every user out. |
| `DJANGO_ALLOWED_HOSTS` | _(empty)_ | **yes** | Hostnames the backend answers to. The public hostname, as Caddy forwards the `Host` header unchanged. `Production` also adds the IP of the container's own hostname (for a load balancer's direct probes). |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | _(empty)_ | no | Origins (`https://host`) trusted for cross-origin POST requests. Not needed when the frontend is served from the same origin as the API, which is what the images do. `Production` only. |
| `DJANGO_ADMIN_URL` | `admin` | no | Path of the Django admin, without slashes. Must be the same value as Caddy's `DJANGO_ADMIN_URL` (see [deployment.md](deployment.md#web-server-environment-variables)). |
| `DJANGO_SERVER_TO_SERVER_API_TOKENS` | _(empty)_ | no | List of bearer tokens accepted by the `ServerToServerAuthentication` class, which no endpoint uses today. |
| `DJANGO_CORS_ALLOW_ALL_ORIGINS` | `false` | no | Allow any origin on the API. Leave off. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | _(empty)_ | no | List of origins allowed on the API. Unnecessary when the frontend is served from the same origin. |
| `DJANGO_CORS_ALLOWED_ORIGIN_REGEXES` | _(empty)_ | no | Same, as a list of regexes. |
| `API_USERS_LIST_THROTTLE_RATE_SUSTAINED` | `180/hour` | no | Rate limit of the users list endpoint. |
| `API_USERS_LIST_THROTTLE_RATE_BURST` | `30/minute` | no | Burst rate limit of the users list endpoint. |

Behind Caddy, the backend trusts `X-Forwarded-Proto` for the request scheme
(`SECURE_PROXY_SSL_HEADER`), redirects plain HTTP to HTTPS and sets HSTS: it
must not be reachable from anywhere but the proxy.

## Database

Either a single URL or the split variables. `DATABASE_URL` wins when set.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | _(unset)_ | one of the two | Database URL, e.g. `postgres://user:password@host:5432/deploycenter`. Parsed by [dj-database-url](https://github.com/jazzband/dj-database-url). |
| `DB_ENGINE` | `django.db.backends.postgresql_psycopg2` | no | Django database backend. The default is Django's alias of `django.db.backends.postgresql`; PostgreSQL is the only supported engine (`django.contrib.postgres` is used). |
| `DB_NAME` | `deploycenter` | one of the two | Database name. |
| `DB_USER` | `dbuser` | one of the two | Database user. |
| `DB_PASSWORD` | `dbpass` | one of the two | Database password. |
| `DB_HOST` | `localhost` | one of the two | Database host. |
| `DB_PORT` | `5432` | no | Database port. |

## Cache and sessions

Sessions live in the cache (`SESSION_ENGINE` is the cache backend, sessions
expire after 12 hours), and the `fetch_proconnect_prevalidated` task shares
its result with the web process through the cache. In `Production` the cache
is Redis: it must be reachable, by the web process and by the
[worker](deployment.md#background-tasks).

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `REDIS_URL` | `redis://redis:6379` | **yes** | Redis URL of the cache, e.g. `redis://:password@host:6379/0` or `rediss://...` for TLS. Restarting Redis without persistence logs every user out. `Production` and `Development` only: the other configurations use an in-memory cache. The task broker has its own URL, `TASK_BROKER_URL`, which may point at the same place. |
| `CACHES_DEFAULT_TIMEOUT` | `30` | no | Default lifetime of a cache entry, in seconds. Sessions and the allowlist cache set their own. |

## OpenID Connect

Authentication goes through an OpenID Connect provider (ProConnect in
production, Keycloak in development) with
[mozilla-django-oidc](https://mozilla-django-oidc.readthedocs.io/). Register the
backend as a client with these URLs, `<origin>` being the public origin of the
deployment:

- redirect URI: `<origin>/api/v1.0/callback/`
- post-logout redirect URI: `<origin>/api/v1.0/logout-callback/`

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `OIDC_RP_CLIENT_ID` | `st_deploycenter` | **yes** | Client ID registered at the provider. |
| `OIDC_RP_CLIENT_SECRET` | _(none)_ | **yes** | Client secret. |
| `OIDC_OP_AUTHORIZATION_ENDPOINT` | _(none)_ | **yes** | Provider's authorization endpoint (the user's browser is sent there). |
| `OIDC_OP_TOKEN_ENDPOINT` | _(none)_ | **yes** | Provider's token endpoint (called by the backend). |
| `OIDC_OP_USER_ENDPOINT` | _(none)_ | **yes** | Provider's userinfo endpoint (called by the backend). |
| `OIDC_OP_JWKS_ENDPOINT` | _(none)_ | **yes** | Provider's JWKS endpoint, to verify the id_token signature (called by the backend). |
| `OIDC_OP_LOGOUT_ENDPOINT` | _(none)_ | no | Provider's end-session endpoint. Unset, logging out only ends the local session. |
| `OIDC_RP_SIGN_ALGO` | `RS256` | no | Signature algorithm of the id_token. |
| `OIDC_RP_SCOPES` | `openid email` | no | Scopes requested. Add the ones carrying the claims of `USER_OIDC_FIELDS_TO_FULLNAME` when they are not in the defaults (ProConnect: `openid email given_name usual_name`). |
| `OIDC_AUTH_REQUEST_EXTRA_PARAMS` | `{}` | no | Dict of extra parameters added to the authorization request, e.g. `{"acr_values": "eidas1"}`. |
| `OIDC_REQUIRE_MFA` | `false` | no | Refuse logins without a second factor and ask the provider for one. See [authentication.md](authentication.md). |
| `OIDC_MFA_ACR_VALUES` | `eidas0-mfa,eidas1-mfa,eidas2,eidas3` | no | List of `acr` values accepted as a second factor when `OIDC_REQUIRE_MFA` is on. |
| `LOGIN_REDIRECT_URL` | _(none)_ | **yes** | Where the browser is sent after a successful login: the frontend URL, `<origin>/`. |
| `LOGIN_REDIRECT_URL_FAILURE` | _(none)_ | **yes** | Where the browser is sent after a failed login. |
| `LOGOUT_REDIRECT_URL` | _(none)_ | **yes** | Where the browser is sent after logging out. |
| `OIDC_REDIRECT_ALLOWED_HOSTS` | _(empty)_ | no | List of hosts allowed in the `next` parameter of the login URL, besides the backend's own. |
| `OIDC_REDIRECT_REQUIRE_HTTPS` | `false` | no | Require HTTPS in the `next` parameter. |
| `OIDC_USE_NONCE` | `true` | no | Send and check a nonce in the authorization request. |
| `OIDC_STORE_ID_TOKEN` | `true` | no | Keep the id_token in the session; needed for the provider logout (`id_token_hint`). |
| `OIDC_CREATE_USER` | `true` | no | Create a local user on first login. Off, only users that already exist can log in. |
| `OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION` | `true` | no | Match an existing user by email when the `sub` claim is unknown. |
| `OIDC_ALLOW_DUPLICATE_EMAILS` | `false` | no | Allow several users with the same email. Cannot be on together with the previous one; not recommended. |
| `USER_OIDC_ESSENTIAL_CLAIMS` | _(empty)_ | no | List of claims a login must carry, refused otherwise. |
| `USER_OIDC_FIELDS_TO_FULLNAME` | `first_name,last_name` | no | List of userinfo claims concatenated into the user's full name, as named by the provider (ProConnect: `given_name,usual_name`). |
| `USER_OIDC_FIELD_TO_SHORTNAME` | `first_name` | no | Declared, not read by the application today. |
| `ALLOW_LOGOUT_GET_METHOD` | `true` | no | Accept `GET` on the logout URL (the frontend uses it). |

## Application

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `API_PUBLIC_URL` | _(none)_ | **yes** | Public URL of the API, with its version and a trailing slash: `<origin>/api/v1.0/`. Used to build the public URLs of the service logos. |
| `SUITE_TERRITORIALE_BASE_URL` | `https://suiteterritoriale.anct.gouv.fr` | no | Base URL of the La Suite territoriale site, for the links built in the entitlements API. |
| `DJANGO_LANGUAGE_CODE` | `fr-fr` | no | Default language. |
| `DJANGO_LANGUAGES` | `fr-fr,French` | no | Available languages, as `code,Name` pairs separated by `;` (e.g. `fr-fr,French;en-us,English`). Only French is translated. |
| `OPERATOR_CONTRIBUTION_POPULATION_THRESHOLD` | `3500` | no | Population from which an operator's contribution is computed. |
| `OPERATOR_CONTRIBUTION_PER_POPULATION` | `0.01` | no | Contribution per inhabitant. |
| `OPERATOR_CONTRIBUTION_MAXIMUM_BASE` | `10000` | no | Cap of the contribution base. |
| `DJANGO_DATA_DIR` | `/data` | no | Directory holding `static/` (the collected static files, served by whitenoise) and `media/` (unused: no model stores a file). The images collect the static files under `/data/static` at build time: do not change it there. |
| `STORAGES_STATICFILES_BACKEND` | `whitenoise.storage.CompressedManifestStaticFilesStorage` | no | Static files storage. The images are built with the default and serve their static files with it; development sets `django.contrib.staticfiles.storage.StaticFilesStorage` to skip the manifest. |
| `SPECTACULAR_SETTINGS_ENABLE_DJANGO_DEPLOY_CHECK` | `false` | no | Run Django's deployment checks when generating the OpenAPI schema. |

## API keys

Each key gates one route; unset, the route is closed to everyone. See
[authentication.md](authentication.md).

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `METRICS_API_KEY` | _(none)_ | no | Bearer key of `GET /api/v1.0/metrics/subscriptions-by-service/`, the active subscriptions of a service. |
| `DOMAINS_API_KEY` | _(none)_ | no | Bearer key of the domains export (`GET /api/v1.0/domains/`), used by the DNS zone generation job. See [domains.md](domains.md). |
| `PROCONNECT_ALLOWLIST_VIEW_API_KEY` | _(none)_ | no | Bearer key of the ProConnect allowlist export (`GET /api/v1.0/proconnect/oidc_providers.yaml`). See [proconnect_domains.md](proconnect_domains.md). |

## ProConnect domains

Push of the authorized email domains to ProConnect's api-partenaires, and
cache of the deployed allowlist. See [proconnect_domains.md](proconnect_domains.md).

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PROCONNECT_API_PARTENAIRES_URL` | _(none)_ | no | Base URL of api-partenaires. Unset, no push happens. |
| `PROCONNECT_API_PARTENAIRES_SECRET` | _(none)_ | no | Secret of api-partenaires, global to all providers. |
| `PROCONNECT_API_PARTENAIRES_PROXY_URL` | _(none)_ | no | SOCKS5 proxy for the api-partenaires calls, e.g. `socks5://user:pass@host:1080`, to egress from a fixed IP. Unset, direct connection. |
| `PROCONNECT_REQUESTED_DOMAIN_WEBHOOKS` | `[]` | no | JSON list of webhooks fired when an operator requests a new domain, same format as the service webhooks. |
| `PROCONNECT_DOMAIN_ALLOWLIST_URL` | the `oidc_providers.production.yaml` of api-partenaires on GitHub | no | URL of the deployed allowlist fetched by `proconnect_fetch_prevalidated`. |
| `PROCONNECT_DOMAIN_ALLOWLIST_CACHE_TTL` | `14400` | no | Lifetime of the fetched allowlist in the cache, in seconds (4 hours). Keep it above the job's period. |

## Domains service

DNS delegation check of the domains declared through the domains service. See
[domains.md](domains.md).

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DOMAINS_NAMESERVERS` | `ns1.lst-domaines.fr,ns2.lst-domaines.fr` | no | List of nameservers a declared domain must be delegated to. |
| `DOMAINS_DNS_TIMEOUT` | `5.0` | no | Timeout of one DNS query, in seconds. |
| `DOMAINS_DNS_MAX_RESOLUTION_TIME` | `15.0` | no | Cap on resolving one name (several queries), in seconds. |

## Background tasks

The worker and its schedule are described in
[deployment.md](deployment.md#background-tasks).

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `TASK_BROKER_URL` | `redis://redis:6379` | **yes** | Redis URL of the task broker, read by the web process (dashboard, enqueue), the worker and the scheduler. **Redis 7.0+**, `maxmemory-policy noeviction`, AOF persistence (see [deployment.md](deployment.md#redis-requirements)). Can be the same instance and database as `REDIS_URL` when that instance does not evict. |
| `TASK_BROKER_NAMESPACE` | `dramatiq` | no | Prefix of every broker key in Redis. |
| `DISABLE_TASK_SCHEDULE` | `false` | no | Register no periodic schedule at all. For a first deploy where the worker starts before the migrations ran. |
| `WORKER_PROCESSES` | `1` | no | Worker processes (`worker.py --processes`). |
| `WORKER_THREADS` | `2` | no | Threads per worker process (`worker.py --threads`). |
| `DATA_GOUV_API_KEY` | _(none)_ | no | API key of data.gouv.fr, needed by the `upload_deployment_datasets` task. |

## Monitoring

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SENTRY_DSN` | _(none)_ | no | Sentry DSN. Unset, Sentry is off. The environment is the configuration name (`production`), the release the `pyproject.toml` version. |
| `LOGGING_LEVEL_LOGGERS_ROOT` | `INFO` | no | Level of the root logger (Django, libraries), on the console. |
| `LOGGING_LEVEL_LOGGERS_APP` | `INFO` | no | Level of the application logger (`core`). |
| `POSTHOG_KEY` | _(none)_ | no | PostHog project key, exposed to the frontend by `GET /api/v1.0/config/`. Unset, analytics are off. |
| `POSTHOG_HOST` | `https://eu.i.posthog.com` | no | PostHog host. |
| `POSTHOG_SURVEY_ID` | _(none)_ | no | PostHog survey shown by the frontend. |

## Minimal production environment

```shellscript
DJANGO_CONFIGURATION=Production
DJANGO_SECRET_KEY=<long random string>
DJANGO_ALLOWED_HOSTS=deploycenter.example.org
DJANGO_ADMIN_URL=admin

DATABASE_URL=postgres://deploycenter:<password>@postgresql:5432/deploycenter
REDIS_URL=redis://redis:6379/0
TASK_BROKER_URL=redis://redis:6379/0

OIDC_RP_CLIENT_ID=<client id>
OIDC_RP_CLIENT_SECRET=<client secret>
OIDC_OP_AUTHORIZATION_ENDPOINT=https://auth.example.org/api/v2/authorize
OIDC_OP_TOKEN_ENDPOINT=https://auth.example.org/api/v2/token
OIDC_OP_USER_ENDPOINT=https://auth.example.org/api/v2/userinfo
OIDC_OP_JWKS_ENDPOINT=https://auth.example.org/api/v2/jwks
OIDC_OP_LOGOUT_ENDPOINT=https://auth.example.org/api/v2/session/end
OIDC_RP_SCOPES="openid email given_name usual_name"
USER_OIDC_FIELDS_TO_FULLNAME=given_name,usual_name
LOGIN_REDIRECT_URL=https://deploycenter.example.org/
LOGIN_REDIRECT_URL_FAILURE=https://deploycenter.example.org/
LOGOUT_REDIRECT_URL=https://deploycenter.example.org/

API_PUBLIC_URL=https://deploycenter.example.org/api/v1.0/
```

## Frontend build-time variables

The frontend is a Next.js static export: its `NEXT_PUBLIC_*` variables are
inlined at build time (`npm run build`, the `frontend-build` stage of
[`src/frontend/Dockerfile`](../src/frontend/Dockerfile)) and **cannot be
changed when deploying an image**. The published images are built with none
of them set.

| Variable | Build argument | Default | Description |
|----------|----------------|---------|-------------|
| `NEXT_PUBLIC_API_ORIGIN` | `API_ORIGIN` | _(empty)_ | Origin the SPA calls the API on. Empty, it uses the origin the page was served from, which Caddy proxies to the backend: the right value for the images. |
| `NEXT_PUBLIC_FEEDBACK_WIDGET_API_URL` | _(none)_ | _(empty)_ | API URL of the feedback widget. The widget is only loaded when the three `FEEDBACK_WIDGET` variables are set. |
| `NEXT_PUBLIC_FEEDBACK_WIDGET_PATH` | _(none)_ | _(empty)_ | Base URL of the widget scripts (`loader.js` and `feedback.js` are appended to it, so it ends with `/`). |
| `NEXT_PUBLIC_FEEDBACK_WIDGET_CHANNEL` | _(none)_ | _(empty)_ | Channel the feedback is posted to. |

The settings the frontend reads at runtime come from the backend, through
`GET /api/v1.0/config/` (`ENVIRONMENT`, `POSTHOG_*`, `LANGUAGES`,
`LANGUAGE_CODE`).
