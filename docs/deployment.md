# Deployment

Deploy Center has two deployment targets. Both serve the frontend with
[Caddy](https://caddyserver.com/), from the same config file,
[`src/frontend/caddy/Caddyfile`](../src/frontend/caddy/Caddyfile): it serves the
Next.js static export and proxies `/api/*`, `/static/*` and the Django admin URL
to the Django backend. The config reads its settings from the environment, so
no templating step is needed.

Whatever the target, the application needs a PostgreSQL database, a Redis
server (cache, sessions and task broker) and an OpenID Connect provider. It
stores no file: no object storage is needed. Besides the web process, a
[worker](#background-tasks) runs the periodic jobs. The backend settings are
documented in [`env.md`](env.md), the web server ones
[below](#web-server-environment-variables).

## Scalingo

The `web` container runs two processes (see `bin/scalingo_run_web`): gunicorn
serving the backend on `localhost:8000`, and Caddy serving the frontend on
`$PORT`. Caddy is downloaded and its config copied at build time by
`bin/scalingo_postfrontend`.

## Container images

Four images, two per side. The `distroless` ones are what production should
run; the `all` ones hold the same content on a base that has a shell, for
debugging.

| Image | Dockerfile target | Base |
|-------|-------------------|------|
| `st-deploycenter-backend-distroless` | `runtime-distroless-prod` | `gcr.io/distroless/cc-debian13` |
| `st-deploycenter-backend-all` | `runtime-prod` | `python:3.13-slim-trixie` |
| `st-deploycenter-frontend-distroless` | `runtime-distroless-prod` | `gcr.io/distroless/static-debian13` |
| `st-deploycenter-frontend-all` | `runtime-prod` | `debian:trixie-slim` |

```shellscript
# build the four images
$ make build-prod-images

# build them and run their smoke tests
$ make test-prod-images

# run the frontend and backend images locally, on http://localhost:8970
$ make run-prod
$ make stop-prod
```

The frontend image listens on 8080 and proxies to
`$DEPLOYCENTER_BACKEND_SERVER`, which points at the backend container
(`backend-prod:8000` in `compose.yaml`). The backend image listens on 8000 and
serves its own static files with whitenoise. Both carry a `HEALTHCHECK`: an
HTTP probe on `/__lbheartbeat__` for the frontend, a TCP connect for the
backend.

`make run-prod` runs the distroless images. Set `BACKEND_PROD_TARGET` or
`FRONTEND_PROD_TARGET` to `runtime-prod` to run the full ones instead.

Migrations are not run by the images:

```shellscript
$ docker compose --profile prod run --rm --build backend-prod python manage.py migrate
```

The backend image also runs the [worker](#background-tasks): same image, same
environment, `python worker.py` as the command instead of gunicorn.

### Published images

[`.github/workflows/docker.yml`](../.github/workflows/docker.yml) builds the
four images for `linux/amd64` and `linux/arm64` and pushes them to the GitHub
registry:

| Image | Flavour | Tags |
|-------|---------|------|
| `ghcr.io/suitenumerique/st-deploycenter-backend` | distroless | `vX.Y.Z`, `latest`, `sha-<short sha>` |
| `ghcr.io/suitenumerique/st-deploycenter-backend` | all | `vX.Y.Z-all`, `latest-all`, `sha-<short sha>-all` |
| `ghcr.io/suitenumerique/st-deploycenter-frontend` | distroless | `vX.Y.Z`, `latest`, `sha-<short sha>` |
| `ghcr.io/suitenumerique/st-deploycenter-frontend` | all | `vX.Y.Z-all`, `latest-all`, `sha-<short sha>-all` |

The plain tags are the distroless images: deploy those. The `-all` suffix
selects the flavour with a shell, for debugging.

`vX.Y.Z` tags come from pushing the git tag of the same name, so the image tag
is the release tag: a tool following the releases of this repository (Renovate
`github-releases` datasource on `suitenumerique/st-deploycenter`) follows the
image tags. `latest` and `sha-*` are pushed on every push to `main` and are
not releases: nothing tests them beyond the CI of the commit.

The frontend image is built with an empty `API_ORIGIN`, so the SPA calls the
API on the origin it was served from, which Caddy proxies (see
[`env.md`](env.md#frontend-build-time-variables)).

### Releasing

The backend reports the version of `src/backend/pyproject.toml` to Sentry, and
the workflow refuses a tag that does not match it. To release `X.Y.Z`:

1. set `version = "X.Y.Z"` in `src/backend/pyproject.toml` and merge it to
   `main`;
2. tag that commit and push the tag:

   ```shellscript
   $ git tag vX.Y.Z
   $ git push origin vX.Y.Z
   ```

The workflow builds and pushes the images. The first push creates the two
packages as private: make them public once, in their settings on GitHub. Create
a GitHub release from the tag if you want release notes. Versions follow semver, with a `v` prefix on the
tag only.

## Background tasks

Every periodic job of the application runs in a **worker** process, from the
backend image, next to the web process:

```shellscript
$ python worker.py
```

It is built on [Dramatiq](https://dramatiq.io/) over the
[dramatiq-redis-streams](https://github.com/sylvinus/dramatiq-redis-streams)
broker (`TASK_BROKER_URL`, see [`env.md`](env.md#background-tasks)), with the
periodic schedule handled by
[dramatiq-crontab](https://github.com/codingjoe/dramatiq-crontab): the
scheduler (`manage.py crontab`) runs inside the worker as a supervised child
process, so there is one process type to deploy and nothing to install on the
host (no cron, no systemd timer). It holds a Redis lock: with several workers,
exactly one scheduler is live and the others stand by to take over. Application
code declares tasks through
[`core/task_utils.py`](../src/backend/core/task_utils.py) and never imports
Dramatiq itself. This is the same stack as
[suitenumerique/messages](https://github.com/suitenumerique/messages).

### Redis requirements

The broker needs **Redis 7.0 or later** (streams, `XREADGROUP`), and the
instance `TASK_BROKER_URL` points at must run with `maxmemory-policy
noeviction` and AOF persistence. A queue is not a cache: under an eviction
policy Redis silently drops stream keys under memory pressure, and enqueued
tasks vanish with no error. The queue here never holds more than a handful of
messages, so it can share the instance of `REDIS_URL` as long as that instance
does not evict; otherwise point `TASK_BROKER_URL` at another database or
instance.

`worker.py` runs one process with two threads by default (`--processes`,
`--threads`, or `WORKER_PROCESSES` / `WORKER_THREADS`); `--disable-scheduler`
runs a worker that only consumes. Start the worker after the migrations have
run: the schedule fires against the database. `DISABLE_TASK_SCHEDULE=true`
registers no schedule at all, for a first deploy to a PaaS where the worker
may start before `migrate`.

The schedule, in UTC (`TIME_ZONE`), is declared on each task with
`@cron_task` and checked by `core/tests/test_tasks_schedule.py`:

| Schedule | Task | What it does |
|----------|------|--------------|
| hourly | `fetch_proconnect_prevalidated` | Caches the deployed ProConnect allowlist, so the UI can tell which domains are pre-validated ([proconnect_domains.md](proconnect_domains.md)). Runs the `proconnect_fetch_prevalidated` management command. |
| daily, 02:00 | `scrape_all_service_metrics` | Fetches the usage metrics of every service. |
| daily, 08:00 | `import_dpnt_dataset` | Imports the DPNT dataset (organizations and their domains). |
| every 4 hours | `upload_deployment_datasets` | Uploads the five deployment datasets to data.gouv.fr (needs `DATA_GOUV_API_KEY`). |
| weekly, Sunday 03:30 | `prune_task_history` | Deletes the task history rows older than a month. |

Tasks do not retry: a failure is reported to Sentry, shows as *failed* in the
task history, and the next scheduled run tries again. Each task has its own
time limit (an hour for the imports and uploads) after which it is
interrupted. The worker needs the database, Redis and outbound HTTPS.

`upload_deployment_datasets` runs `upload_deployment_services_dataset`,
`upload_deployment_operators_dataset`, `upload_deployment_adherents_dataset`,
`upload_deployment_subscriptions_dataset` and `upload_deployment_metrics_dataset`
in that order, goes on after a failure and fails at the end if any did. It is
memory-hungry (the CSVs are built in memory): size the worker accordingly.

### Delivery semantics

Delivery is **at-least-once**. The broker acks a message only once the task has
returned, so a worker killed mid-run — a deploy, an OOM kill, a lost host —
does not lose the job: the message is handed to another worker and the task
runs again. The price of not losing work is that it can be done twice.

A task's `time_limit` is also that recovery deadline: once a message has been
held for its own limit plus a ten-second grace, the next recovery sweep treats
it as orphaned and re-delivers it, whether or not the original worker is still
chewing on it. A task that routinely outlives its limit is therefore a task
that routinely runs twice — raise the limit rather than let it overrun. A task
that declares none would be reclaimed after ten minutes, which is why
`register_task` makes it mandatory.

**Every task must be safe to run twice**, and the current ones are: the
data.gouv.fr uploads POST to a fixed resource id, so a second run replaces the
same file with the same content; the metrics scrape upserts its rows
(`bulk_create(update_conflicts=True)`); the DPNT import looks each
organization up before writing it and inserts subscriptions and roles with
`ignore_conflicts`; the ProConnect fetch only fills a cache; the history prune
deletes by age. A new task that is not naturally idempotent has to guard itself
(a lock, a watermark, a uniqueness constraint) — it cannot rely on being run
once.

Two things keep a duplicate run rare rather than routine. Workers reserve one
message per consumer thread instead of Dramatiq's default of two
(`dramatiq_queue_prefetch=1`, set in `worker.py`), so no message sits reserved,
ageing towards its deadline, behind the hour-long import running next to it.
And the worker consumes a single queue, so there is no long job on one queue
stranding a short one on another.

### Writing a task

Tasks are declared through
[`core/task_utils.py`](../src/backend/core/task_utils.py) — application code
never imports Dramatiq — in a module of `core/tasks/` imported by its
`__init__.py`, which is what the worker and the scheduler autodiscover
(`DRAMATIQ_AUTODISCOVER_MODULES`):

```python
from ..task_utils import cron_task, register_task


@cron_task("0 8 * * *")
@register_task(time_limit=3600)
def import_dpnt_dataset():
    ...
```

- `@register_task` needs an explicit **`time_limit` in seconds**: pick a budget
  above the worst run you expect (see [above](#delivery-semantics)), after
  which a `TimeLimitExceeded` is raised inside the task. `max_retries` is `0`,
  so a failure dead-letters at once and is reported to Sentry instead of
  hammering a broken dependency for the rest of the day; raise it per task if
  a retry is what you want. Arguments must be JSON-serializable: pass ids, not
  model instances.
- `@cron_task` goes **above** it, with a five-field cron expression read in
  `TIME_ZONE` (UTC); its day-of-week field must be a literal (`Mon`...`Sun`) or
  `*`. Only the scheduler acts on it, so registering a schedule in the web
  process is inert.
- Add the task to `core/tasks/__init__.py` and its schedule to `SCHEDULE` in
  [`core/tests/test_tasks_schedule.py`](../src/backend/core/tests/test_tasks_schedule.py),
  which asserts the schedule table of this page — and add the row to that
  table.

Calling the function directly runs it inline in the current process (what the
tests and `manage.py run_task` do); `.send()` enqueues it for the worker.

### Monitoring

Every run of a task is a row in the Django admin, under *Django Dramatiq >
Tasks*, with its status (enqueued, running, done, failed with the traceback):
this is where to check that a schedule fired.

The live state of the broker is on the **task dashboard**, served from the
Django admin at `/<DJANGO_ADMIN_URL>/tasks/` (`/admin/tasks/` by default;
[`core/task_dashboard.py`](../src/backend/core/task_dashboard.py)): per-queue
backlog and throughput, the workers and what they hold, delayed messages, and
the dead-letter queue with requeue and purge actions. The dashboard itself
performs no authentication and exposes destructive endpoints, so it is only
reachable:

- with an active **staff session** (it is wrapped in the admin's own
  `admin_view`, anonymous requests get the admin login page);
- from the **admin IP allowlist** of the Caddy proxy: being under the admin
  URL, it is covered by `DEPLOYCENTER_ADMIN_IP_ALLOWLIST` and
  `DEPLOYCENTER_TRUSTED_PROXIES` like the rest of the admin (see
  [below](#restricting-the-django-admin-to-a-set-of-ips)), so a VPN-only admin
  is a VPN-only dashboard;
- for its buttons (flush, purge, requeue), from a page of this host: they
  POST without a CSRF token, and the view requires the `Origin` (or `Referer`)
  to match the host instead.

It only exists with the Streams broker: the tests and `DevelopmentMinimal`
run an in-process broker and have no route for it.

### Running a task by hand

The scheduled tasks can also be run synchronously, in the current process,
outside their schedule:

```shellscript
$ python manage.py run_task import_dpnt_dataset
$ python manage.py run_task scrape_service_metrics --pargs '[59]'
# the five uploads, or only some of them
$ python manage.py upload_deployment_datasets
$ python manage.py upload_deployment_datasets upload_deployment_metrics_dataset
$ python manage.py proconnect_fetch_prevalidated
```

These are single executables with arguments, no shell needed, so they run
as-is in the distroless image (`podman run --rm <backend image> python
manage.py run_task ...`). Do not run one while the worker may be running the
same task: they are not designed to overlap with themselves.

On Scalingo, the worker is the `worker` process type of the `Procfile`. The
app declares no platform cron (no `cron.json`): the schedule lives in the
worker, and database backups are handled outside this repository.

## Web server environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` in the images, set by the platform on Scalingo | Port Caddy listens on. Do not change it in the images: their `HEALTHCHECK` hardcodes 8080. |
| `DEPLOYCENTER_FRONTEND_ROOT` | `/app` in the images, `/app/build/frontend-out` on Scalingo | Directory of the built frontend files that Caddy serves. |
| `DEPLOYCENTER_BACKEND_SERVER` | `localhost:8000` | `host:port` of the Django backend. |
| `DJANGO_ADMIN_URL` | `admin` | Django's admin URL, which Caddy proxies and filters. The same value goes to the backend and to the frontend: Django adds the trailing slash it needs itself (`deploycenter/urls.py`), so write it without one. Never set it empty: Caddy only falls back to the default when a variable is unset, and an empty one turns the admin matchers into `/` and `//*`. |
| `DEPLOYCENTER_ADMIN_IP_ALLOWLIST` | `0.0.0.0/0 ::/0` | Space-separated CIDR list of client IPs allowed on the Django admin URL. The default allows all (no filtering). Caddy answers 403 to denied requests. |
| `DEPLOYCENTER_TRUSTED_PROXIES` | _(empty)_ | Space-separated CIDR list of upstream proxies whose `X-Forwarded-For` sets the client IP. Empty = trust no proxy, the client IP is then the TCP peer. Caddy walks the header from right to left and takes the first address that is not a trusted proxy. |

## Restricting the Django admin to a set of IPs

Set `DEPLOYCENTER_ADMIN_IP_ALLOWLIST` to the allowed CIDRs, and
`DEPLOYCENTER_TRUSTED_PROXIES` to the proxies in front of Caddy,
otherwise the allowlist is compared against the proxy address instead of the
client one.

On Scalingo, the routers set `X-Forwarded-For` and the container port is only
reachable through them, but their IP ranges are not published. Set
`DEPLOYCENTER_TRUSTED_PROXIES=private_ranges` there: the Caddy keyword
covers the private ranges the routers use. Do not use `private_ranges` when
untrusted machines share the private network with Caddy.

To turn the filter off, leave `DEPLOYCENTER_ADMIN_IP_ALLOWLIST` unset. Do not set it
to an empty value: an empty list matches no client IP, so Caddy answers 403 to
every admin request.

`bin/smoke_test_front <image>` covers this on a built frontend image: the
allowlist, spoofed `X-Forwarded-For` headers, and the trusted proxy modes.
