# Image for Anthropic's OSS Scanner. See .oss-scanner/threat_model.md.
# The scan runs with no network, so this build installs every dependency.
# Scanner contract: the repository is the build context, the checkout is /src.
FROM debian:trixie-slim@sha256:28de0877c2189802884ccd20f15ee41c203573bd87bb6b883f5f46362d24c5c2

# initdb reads the locale when the postgresql package creates its cluster.
# Without a UTF-8 locale the cluster gets the SQL_ASCII encoding.
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# policy-rc.d stops the postgresql package from starting a server: a server
# killed at the end of a layer leaves a stale pid file in the image.
RUN <<EOR
set -eux
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    libnss-myhostname \
    postgresql-17 \
    python3
rm -f /usr/sbin/policy-rc.d
rm -rf /var/lib/apt/lists/*
# settings.py resolves the hostname at import time. With no network and no
# DNS, only the myhostname NSS module makes that lookup succeed.
sed -i 's/^hosts:.*/hosts: files myhostname dns/' /etc/nsswitch.conf
# core/migrations/0003 creates these two extensions.
test -f /usr/share/postgresql/17/extension/pg_trgm.control
test -f /usr/share/postgresql/17/extension/unaccent.control
pg_lsclusters
EOR

# The cluster holds test data only. postgresql.conf includes conf.d.
RUN printf '%s\n' \
      "listen_addresses = 'localhost'" \
      "fsync = off" \
      "full_page_writes = off" \
      "synchronous_commit = off" \
      "max_connections = 200" \
      > /etc/postgresql/17/main/conf.d/oss-scanner.conf

# The scanner replaces ENTRYPOINT and CMD, so the image cannot start the
# server itself. pgctl starts it, and every shell sources the init file.
COPY --chmod=0755 <<'EOF' /usr/local/bin/pgctl
#!/bin/sh
set -eu

ready() {
    pg_isready -q -h 127.0.0.1 -p 5432
}

case "${1:-start}" in
start)
    if ready; then exit 0; fi
    install -d -o postgres -g postgres -m 2775 /var/run/postgresql
    install -d -o postgres -g postgres -m 1775 /var/log/postgresql
    # A build layer that sourced the shell init file leaves this file behind.
    pid=/var/lib/postgresql/17/main/postmaster.pid
    if [ -f "$pid" ] && ! kill -0 "$(head -n 1 "$pid")" 2>/dev/null; then
        rm -f "$pid"
    fi
    pg_ctlcluster 17 main start
    i=0
    while [ "$i" -lt 60 ]; do
        if ready; then exit 0; fi
        sleep 0.5
        i=$((i + 1))
    done
    echo "pgctl: postgresql did not become ready" >&2
    exit 1
    ;;
stop)
    pg_ctlcluster 17 main stop || true
    ;;
status)
    pg_lsclusters
    ;;
psql)
    shift
    exec runuser -u postgres -- psql "$@"
    ;;
*)
    echo "usage: pgctl [start|stop|status|psql]" >&2
    exit 2
    ;;
esac
EOF

# Sourced by BASH_ENV, /etc/profile.d and /root/.bashrc. It must stay silent
# and must not change the exit status.
COPY --chmod=0644 <<'EOF' /etc/oss-scanner-shell-init
if [ -z "${OSS_SCANNER_PG_STARTED:-}" ]; then
    if /usr/local/bin/pgctl start >/dev/null 2>&1; then
        OSS_SCANNER_PG_STARTED=1
        export OSS_SCANNER_PG_STARTED
    fi
fi
:
EOF

# Same Node major as src/frontend/Dockerfile. A bookworm binary runs on trixie.
COPY --from=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN <<EOR
set -eux
ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
node --version
npm install -g npm@11.6.2
npm --version
EOR

# uv and the managed CPython, as in src/backend/Dockerfile.
COPY --from=ghcr.io/astral-sh/uv@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed

RUN uv python install 3.14.7

# No cache mount: a cache mount is not kept in the image, and the agent needs
# the download caches to install anything with no network.
COPY src/backend/pyproject.toml src/backend/uv.lock /src/src/backend/
RUN cd /src/src/backend && uv sync --frozen --no-install-project --no-editable --all-extras

COPY src/frontend/package.json src/frontend/package-lock.json /src/src/frontend/
RUN cd /src/src/frontend && npm ci --no-audit --no-fund

COPY . /src
WORKDIR /src

ENV PATH=/venv/bin:$PATH

# pytest runs with --import-mode=importlib, so PYTHONPATH must hold the
# backend root. The other values mirror env.d/development/backend.defaults.
# They are the public development values, not secrets.
ENV VIRTUAL_ENV=/venv \
    PYTHONPATH=/src/src/backend \
    DJANGO_SETTINGS_MODULE=deploycenter.settings \
    DJANGO_CONFIGURATION=Test \
    DJANGO_SECRET_KEY=ThisIsAnExampleKeyForDevPurposeOnly \
    DJANGO_ALLOWED_HOSTS=* \
    DJANGO_DATA_DIR=/data \
    DB_HOST=127.0.0.1 \
    DB_PORT=5432 \
    DB_NAME=deploycenter \
    DB_USER=user \
    DB_PASSWORD=pass \
    API_PUBLIC_URL=http://localhost:8961/api/v1.0/ \
    MEDIA_BASE_URL=http://localhost:8902 \
    FRONTEND_THEME=dsfr \
    OIDC_OP_JWKS_ENDPOINT=http://keycloak:8802/realms/deploycenter/protocol/openid-connect/certs \
    OIDC_OP_AUTHORIZATION_ENDPOINT=http://localhost:8962/realms/deploycenter/protocol/openid-connect/auth \
    OIDC_OP_TOKEN_ENDPOINT=http://keycloak:8802/realms/deploycenter/protocol/openid-connect/token \
    OIDC_OP_USER_ENDPOINT=http://keycloak:8802/realms/deploycenter/protocol/openid-connect/userinfo \
    OIDC_RP_CLIENT_ID=deploycenter \
    OIDC_RP_CLIENT_SECRET=ThisIsAnExampleKeyForDevPurposeOnly \
    OIDC_RP_SIGN_ALGO=RS256 \
    OIDC_RP_SCOPES="openid email" \
    OIDC_REDIRECT_ALLOWED_HOSTS='["http://localhost:8962"]' \
    OIDC_AUTH_REQUEST_EXTRA_PARAMS='{"acr_values": "eidas1"}' \
    LOGIN_REDIRECT_URL=http://localhost:8960 \
    LOGIN_REDIRECT_URL_FAILURE=http://localhost:8960 \
    LOGOUT_REDIRECT_URL=http://localhost:8960 \
    NEXT_TELEMETRY_DISABLED=1

# "user" needs the quotes: it is a reserved word in SQL. CI collects the
# static files before the tests because the Test configuration uses the
# whitenoise manifest storage.
RUN <<EOR
set -eux
install -d -m 0777 /data /data/static /data/media
pgctl start
test "$(runuser -u postgres -- psql -tAXc 'show server_encoding')" = UTF8
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -X \
    -c "CREATE ROLE \"${DB_USER}\" LOGIN SUPERUSER CREATEDB PASSWORD '${DB_PASSWORD}';"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -X \
    -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"
cd /src/src/backend
python manage.py migrate --noinput
python manage.py collectstatic --noinput
pgctl stop
EOR

# A failing test must not fail the build. --reuse-db keeps the migrated test
# databases in the image: one per xdist worker, and the serial one that the
# second run creates for the agent's first `pytest --reuse-db`. The two
# scraping test files bind the fixed port 8001, so they run in the serial pass.
RUN <<EOR
set -eux
pgctl start
cd /src/src/backend
timeout 1500 pytest --reuse-db -p no:cacheprovider -n auto \
    --ignore=core/tests/test_metrics_scraping.py \
    --ignore=core/tests/test_usage_metrics_scraping.py \
    || echo "WARNING: the parallel test run did not finish cleanly (exit $?)"
timeout 600 pytest --reuse-db -p no:cacheprovider -q core/tests/models \
    core/tests/test_metrics_scraping.py core/tests/test_usage_metrics_scraping.py \
    || echo "WARNING: the serial test run did not finish cleanly (exit $?)"
pgctl stop
EOR

# A half-written .next blocks every later build, so a failure removes it.
RUN <<EOR
set -eux
cd /src/src/frontend
timeout 600 npm run build || { echo "WARNING: the frontend build failed"; rm -rf .next out; }
EOR

RUN <<EOR
set -eux
echo '. /etc/oss-scanner-shell-init' > /etc/profile.d/oss-scanner.sh
echo '. /etc/oss-scanner-shell-init' >> /root/.bashrc
git config --system --add safe.directory /src
python -c 'import socket; socket.gethostbyname(socket.gethostname())'
EOR

# From here on every tool reads the caches in this image and fails fast
# instead of waiting for a network that is not there.
ENV BASH_ENV=/etc/oss-scanner-shell-init \
    NO_UPDATE_NOTIFIER=1 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_OFFLINE=true \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PIP_NO_INDEX=1 \
    UV_FROZEN=1 \
    UV_NO_SYNC=1 \
    UV_OFFLINE=1
