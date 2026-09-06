ARG FRONTEND_IMAGE=frontend-build-output

FROM node:22-slim AS frontend-base

WORKDIR /home/frontend/

RUN npm install -g npm@11.6.2 && npm cache clean -f

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

# ---- Web server binaries ----
FROM alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d AS tools-download
ARG TARGETARCH

ARG CADDY_VERSION=2.11.4
# When upgrading, run
# for arch in amd64 arm64; do printf "CADDY_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_linux_${arch}.tar.gz" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly (also in bin/scalingo_postfrontend)
ARG CADDY_SHA256_AMD64=527fbf917c39189a1e3b31d34fa955601680b2d5c8055d2a87b8b9588dec7bb9
ARG CADDY_SHA256_ARM64=52d42ae12b3462097e9868da6dfed3c9648ae12edd3b3638102312af84cb6904
RUN wget -qO /tmp/caddy.tar.gz "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${TARGETARCH}.tar.gz" \
    && case "${TARGETARCH}" in \
         amd64) echo "${CADDY_SHA256_AMD64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         arm64) echo "${CADDY_SHA256_ARM64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && tar -xzf /tmp/caddy.tar.gz caddy \
    && mv caddy /usr/bin/caddy \
    && rm /tmp/caddy.tar.gz

# HTTP probe for the healthcheck: the distroless image has no shell and no curl.
ARG LPROBE_VERSION=v0.2.0
# When upgrading, run
# for arch in amd64 arm64; do printf "LPROBE_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/fivexl/lprobe/releases/download/v0.2.0/lprobe-linux-${arch}" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly
ARG LPROBE_SHA256_AMD64=8b55ddb15c2d8c5e1773c73c1413b26c7041e5836dabdbcef5f806ba6b9d17a2
ARG LPROBE_SHA256_ARM64=3f31eee19167f23dc64c645021b75306956da245e5b9763c90abd12797d0a72a
RUN wget -qO /usr/bin/lprobe "https://github.com/fivexl/lprobe/releases/download/${LPROBE_VERSION}/lprobe-linux-${TARGETARCH}" \
    && case "${TARGETARCH}" in \
         amd64) echo "${LPROBE_SHA256_AMD64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         arm64) echo "${LPROBE_SHA256_ARM64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && chmod +x /usr/bin/lprobe

# ---- Production runtime, full image ----
# Same content as the distroless target below, on a base that has a shell.
FROM debian:trixie-slim AS runtime-prod

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY --from=tools-download /usr/bin/caddy /usr/bin/caddy
COPY --from=tools-download /usr/bin/lprobe /usr/bin/lprobe
COPY --from=frontend-source /app /app
COPY caddy/Caddyfile /etc/caddy/Caddyfile

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
FROM gcr.io/distroless/static-debian13:nonroot AS runtime-distroless-prod

COPY --from=tools-download /usr/bin/caddy /usr/bin/caddy
COPY --from=tools-download /usr/bin/lprobe /usr/bin/lprobe
COPY --from=frontend-source /app /app
COPY caddy/Caddyfile /etc/caddy/Caddyfile

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
