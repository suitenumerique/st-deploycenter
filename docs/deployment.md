# Deployment

Deploy Center has two deployment targets. Both serve the frontend with
[Caddy](https://caddyserver.com/), from the same config file,
[`src/frontend/caddy/Caddyfile`](../src/frontend/caddy/Caddyfile): it serves the
Next.js static export and proxies `/api/*`, `/static/*` and the Django admin URL
to the Django backend. The config reads its settings from the environment, so
no templating step is needed.

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

## Web server environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` in the images, set by the platform on Scalingo | Port Caddy listens on. Do not change it in the images: their `HEALTHCHECK` hardcodes 8080. |
| `DEPLOYCENTER_FRONTEND_ROOT` | `/app` in the images, `/app/build/frontend-out` on Scalingo | Directory of the built frontend files that Caddy serves. |
| `DEPLOYCENTER_BACKEND_SERVER` | `localhost:8000` | `host:port` of the Django backend. |
| `DEPLOYCENTER_ADMIN` | `admin` | Admin path proxied to Django, without the surrounding slashes. `bin/scalingo_run_web` derives it from `DJANGO_ADMIN_URL`, so on Scalingo set that one instead. Never set it to an empty value: Caddy only falls back to the default when a variable is unset, and an empty one turns the admin matchers into `/` and `//*`. |
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
