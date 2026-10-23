ARG FRONTEND_IMAGE=frontend-build-output

FROM node:24.22.1-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS frontend-base

# Bump to force an apt refresh + security upgrade of the base OS.
ENV MIN_UPDATE_DATE="2026-10-24"

RUN <<EOR
set -eu
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get upgrade -y
DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
    ca-certificates
rm -rf /var/lib/apt/lists/*
EOR

# Node trusts its own bundled root list, which lags behind Debian's; make it
# use the system store instead so CA updates come with the apt upgrade above.
ENV NODE_OPTIONS=--use-openssl-ca
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /home/frontend/

RUN npm install -g npm@11.21.1 && npm cache clean -f

# ---- Development / tooling image (see compose.yaml) ----
# The sources are bind-mounted and npm runs as the host user.
FROM frontend-base AS frontend-dev

ARG DOCKER_USER
USER ${DOCKER_USER}

ENV npm_config_cache=/tmp/npm-cache

# ---- Production dependencies ----
# Only for the production build below: the dev image installs its dependencies
# in the bind-mounted source tree instead.
FROM frontend-base AS frontend-deps

COPY package.json package-lock.json ./
RUN npm ci

# ---- Production build ----
FROM frontend-deps AS frontend-build

COPY . ./

# Origin the SPA calls the API on. Left empty, it falls back to the origin the
# page was served from (see src/features/api/utils.ts), which is what the
# images below serve: Caddy proxies /api/ to the backend.
ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN npm run build

# Normalize the output path to /app (matches the runtime layout below)
FROM scratch AS frontend-build-output
COPY --from=frontend-build /home/frontend/out /app

# When FRONTEND_IMAGE is set to an external image, BuildKit skips
# frontend-deps, frontend-build and frontend-build-output entirely
FROM ${FRONTEND_IMAGE} AS frontend-source

# ---- Caddy sources ----
# src/caddy of the repository, outside this build context: the build passes it as
# the named context "caddy-src" (`--build-context` in the Makefile,
# `additional_contexts` in compose.yaml), which replaces this empty stage. A
# build without it fails on the first COPY from this stage.
FROM scratch AS caddy-src

# ---- Caddy, built from source ----
# Only the modules src/caddy/main.go lists, with the flags of src/caddy/build.sh,
# so the Go toolchain and the dependencies are ours to update: the go directive
# of src/caddy/go.mod, this image and the tarball in bin/scalingo_postfrontend
# must stay on the same Go version (build.sh checks it). Runs on the build
# platform and cross-compiles, so a multi-arch build does not go through
# emulation.
FROM --platform=$BUILDPLATFORM golang:1.27.3@sha256:f20d83a83e18dbd2a4714b8ffd4b30b287b6243962dd75608e86abcc63ba4efc AS caddy-build
ARG TARGETOS
ARG TARGETARCH

WORKDIR /src
COPY --from=caddy-src go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY --from=caddy-src / ./
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    GOOS=${TARGETOS} GOARCH=${TARGETARCH} sh build.sh /out/caddy

# ---- Health check probe ----
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS tools-download
ARG TARGETARCH

RUN <<EOR
set -eu
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
    ca-certificates \
    wget
rm -rf /var/lib/apt/lists/*
EOR

# HTTP probe for the healthcheck: the distroless image has no shell and no curl.
ARG LPROBE_VERSION=v0.2.1
# When upgrading, run
# for arch in amd64 arm64; do printf "LPROBE_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/fivexl/lprobe/releases/download/v0.2.1/lprobe-linux-${arch}" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly
ARG LPROBE_SHA256_AMD64=6af14d9c2f71e81357d481088791c0744254877b43de337710c5200d3fc5fb48
ARG LPROBE_SHA256_ARM64=b32dc4863c5879527a916161daff334213834d979e2cdeb2f214f72425d63c20
RUN wget -qO /usr/bin/lprobe "https://github.com/fivexl/lprobe/releases/download/${LPROBE_VERSION}/lprobe-linux-${TARGETARCH}" \
    && case "${TARGETARCH}" in \
         amd64) echo "${LPROBE_SHA256_AMD64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         arm64) echo "${LPROBE_SHA256_ARM64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && chmod +x /usr/bin/lprobe

# ---- Production runtime, full image ----
# Same content as the distroless target below, on a base that has a shell.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS runtime-prod

# Bump to force an apt refresh + security upgrade of the base OS.
ENV MIN_UPDATE_DATE="2026-10-24"

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY --from=caddy-build /out/caddy /usr/bin/caddy
COPY --from=tools-download /usr/bin/lprobe /usr/bin/lprobe
COPY --from=frontend-source /app /app
COPY --from=caddy-src Caddyfile /etc/caddy/Caddyfile

ENV PORT=8080
ENV DEPLOYCENTER_FRONTEND_ROOT=/app
ENV DEPLOYCENTER_BACKEND_SERVER=localhost:8000
# DJANGO_ADMIN_URL is not declared here: the Caddyfile defaults it to "admin".
# Set it (without a trailing slash) on this container and on the backend one
# when the Django admin URL is not the default.
# Caddy stores its state under XDG_DATA_HOME; the unprivileged user below has
# no writable home directory.
ENV XDG_DATA_HOME=/tmp
ENV XDG_CONFIG_HOME=/tmp

USER nobody
EXPOSE 8080

ENTRYPOINT ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

# Port is hardcoded below because the distroless image has no shell to expand
# $PORT. If you change ENV PORT above, update the healthcheck port to match.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["/usr/bin/lprobe", "-mode=http", "-port=8080", "-endpoint=/__lbheartbeat__"]

# ---- Production runtime, distroless ----
FROM gcr.io/distroless/static-debian13:nonroot@sha256:18f4cc26c9ffa7f20a359298be7deadac5c607c8e03a02b8119f1a5fc2f82c99 AS runtime-distroless-prod

COPY --from=caddy-build /out/caddy /usr/bin/caddy
COPY --from=tools-download /usr/bin/lprobe /usr/bin/lprobe
COPY --from=frontend-source /app /app
COPY --from=caddy-src Caddyfile /etc/caddy/Caddyfile

ENV PORT=8080
ENV DEPLOYCENTER_FRONTEND_ROOT=/app
ENV DEPLOYCENTER_BACKEND_SERVER=localhost:8000
# DJANGO_ADMIN_URL is not declared here: the Caddyfile defaults it to "admin".
# Set it (without a trailing slash) on this container and on the backend one
# when the Django admin URL is not the default.
ENV XDG_DATA_HOME=/tmp
ENV XDG_CONFIG_HOME=/tmp

EXPOSE 8080

ENTRYPOINT ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["/usr/bin/lprobe", "-mode=http", "-port=8080", "-endpoint=/__lbheartbeat__"]
