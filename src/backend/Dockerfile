# Debian pinned by digest so the base cannot move under us between builds.
FROM debian:trixie-slim@sha256:28de0877c2189802884ccd20f15ee41c203573bd87bb6b883f5f46362d24c5c2 AS base

# Bump this to force an update of the apt repositories
ENV MIN_UPDATE_DATE="2026-09-14"

RUN <<EOR
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get upgrade -y
DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
    ca-certificates
rm -rf /var/lib/apt/lists/*
EOR

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ---- uv and the managed CPython the whole build runs on ----
FROM base AS uv

# uv pinned by SHA256 digest for supply chain security (uv 0.12.13).
# Verify with: gh attestation verify --owner astral-sh oci://ghcr.io/astral-sh/uv:0.12.13
COPY --from=ghcr.io/astral-sh/uv@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_PREFERENCE=only-managed
ENV UV_PYTHON_INSTALL_DIR=/opt/python
ENV UV_PROJECT_ENVIRONMENT=/venv

# Integrity is verified against SHA256 checksums embedded in the uv binary.
# python-build-standalone statically links most C deps (ssl, ffi, sqlite, zlib).
RUN uv python install 3.14.7

COPY --chmod=0755 strip-python.sh /usr/local/bin/strip-python

# ---- Build-only system deps ----
# Kept in this stage alone so no compiler reaches a runtime image. rdfind is used
# by the static link collector below.
FROM uv AS uv-build

RUN <<EOR
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
    curl \
    rdfind \
    build-essential
rm -rf /var/lib/apt/lists/*
EOR

# ---- Base image with dependencies installed ----
FROM uv-build AS base-with-deps

COPY pyproject.toml uv.lock ./

ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV=/venv
ENV VIRTUAL_ENV_PROMPT=venv

# --no-install-project: the backend is an application, there is no package to
# build (see [tool.uv] package = false).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-editable --exact --no-dev

# ---- Base image with dependencies installed for development ----
FROM base-with-deps AS base-with-deps-dev

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-editable --all-extras

# ---- static link collector ----
FROM base-with-deps AS link-collector
ARG DEPLOYCENTER_STATIC_ROOT=/data/static

# Copy deploycenter application (see .dockerignore)
COPY . /app/

WORKDIR /app

# collectstatic
RUN DJANGO_CONFIGURATION=Build \
    python manage.py collectstatic --noinput

# Replace duplicated file by a symlink to decrease the overall size of the
# final image
RUN rdfind -makesymlinks true -followsymlinks true -makeresultsfile false ${DEPLOYCENTER_STATIC_ROOT}


# ---- Production application source (strip tests and build files) ----
FROM base AS app-prod

COPY . /app/

# pyproject.toml stays: settings.get_release() reads the version from it.
RUN rm -rf \
    /app/core/tests \
    /app/core/factories.py \
    /app/Dockerfile \
    /app/uv.lock \
    /app/strip-python.sh \
    /app/entrypoint

# COPY keeps the modes of the build context, and the runtime images run as an
# unprivileged user that does not own these files: a file left group/other
# unreadable in a working copy would only fail once imported at runtime.
RUN chmod -R a+rX /app


# ---- Base runtime image ----
# FROM uv, not base: the interpreter is the uv-managed one under /opt/python, and
# /venv's symlinks point into it.
FROM uv AS runtime-base

# Give the "root" group the same permissions as the "root" user on /etc/passwd
# to allow a user belonging to the root group to add new users; typically the
# docker user (see entrypoint).
RUN chmod g=u /etc/passwd

# Un-privileged user running the application
ARG DOCKER_USER=1000
USER ${DOCKER_USER}

ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV=/venv
ENV VIRTUAL_ENV_PROMPT=venv

# We wrap commands run in this container by the following entrypoint that
# creates a user on-the-fly with the container user ID (see USER) and root group
# ID.
COPY ./entrypoint /usr/local/bin/entrypoint
ENTRYPOINT [ "/usr/local/bin/entrypoint" ]


# ---- Base runtime image for development ----
FROM runtime-base AS runtime-dev

COPY --from=base-with-deps-dev /venv /venv

# /app will be mounted as a volume in the development container

# Target database host (e.g. database engine following docker compose services
# name) & port
# ENV DB_HOST=postgresql \
#     DB_PORT=5432

# Run django development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# ---- Base runtime image for production ----
FROM runtime-base AS runtime-prod
# Declared again: an ARG only lives in the stage that declares it, and an empty
# value here makes the COPY below copy the whole link-collector filesystem.
ARG DEPLOYCENTER_STATIC_ROOT=/data/static

COPY --from=base-with-deps /venv /venv

COPY --from=link-collector ${DEPLOYCENTER_STATIC_ROOT} ${DEPLOYCENTER_STATIC_ROOT}

COPY --from=app-prod /app/ /app/

EXPOSE 8000

# The default command runs gunicorn WSGI server in deploycenter's main module
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "deploycenter.wsgi:application"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s \
  CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=2).close()"]


# ---- System libraries needed by the interpreter and the C extensions ----
# Everything under /venv (the psycopg wheel ships its own libpq) and
# /usr/local (libpython) is copied as a whole, only system libraries are
# collected here.
FROM base-with-deps AS shared-libs

# Version-agnostic: the interpreter path comes from uv rather than a hardcoded
# python3.NN, so a Python bump does not silently produce an image missing
# libraries.
RUN <<EOR
set -eu
PYBIN=$(uv python find)
PYDIR=$(dirname "$(dirname "$PYBIN")")
mkdir -p /shared-libs/usr/lib
{ ldd "$PYBIN"; \
  find "$PYDIR"/lib/python3.*/lib-dynload /venv/lib -name '*.so*' -exec ldd {} + ; } 2>/dev/null \
  | awk '/=> \//{print $3}' | sort -u \
  | grep -Ev '^(/venv|/opt/python)/' \
  | xargs -r -I{} cp -L {} /shared-libs/usr/lib/
EOR


# ---- Python installation without pip, headers and test modules ----
FROM uv AS python-stripped

RUN strip-python


# ---- Distroless runtime image for production ----
# cc-debian13 provides glibc, libgcc and libstdc++; every other system library
# the interpreter and the C extensions need comes from the shared-libs stage.
# Debug with: docker run --entrypoint='' gcr.io/distroless/cc-debian13:debug-nonroot sh
FROM gcr.io/distroless/cc-debian13:nonroot AS runtime-distroless-prod
ARG DEPLOYCENTER_STATIC_ROOT=/data/static

WORKDIR /app

COPY --from=python-stripped /opt/python /opt/python
COPY --from=base-with-deps /venv /venv
COPY --from=shared-libs /shared-libs/ /
COPY --from=link-collector ${DEPLOYCENTER_STATIC_ROOT} ${DEPLOYCENTER_STATIC_ROOT}
COPY --from=app-prod /app/ /app/

ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV=/venv
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Distroless has no ldconfig cache: tell the dynamic linker where the system
# libraries copied above are.
ENV LD_LIBRARY_PATH=/usr/lib

EXPOSE 8000

CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "deploycenter.wsgi:application"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s \
  CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=2).close()"]
