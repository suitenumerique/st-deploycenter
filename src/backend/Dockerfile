# https://hub.docker.com/_/python
FROM python:3.13.7-slim-trixie AS base

# Bump this to force an update of the apt repositories
ENV MIN_UPDATE_DATE="2025-08-29"

RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ---- Poetry package manager and dev system deps ----
FROM base AS poetry

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    rdfind \
    && rm -rf /var/lib/apt/lists/*

ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_CREATE=0
ENV POETRY_VIRTUALENVS_OPTIONS_NO_PIP=1
ENV POETRY_VERSION=2.1.4

RUN python -m pip install poetry==${POETRY_VERSION}

# ---- Base image with dependencies installed ----
FROM poetry AS base-with-deps

COPY pyproject.toml poetry.lock ./

# Create a runtime virtual environment and activate it
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV=/venv
ENV VIRTUAL_ENV_PROMPT=venv

# Install dependencies in this new virtual environment
RUN poetry install --compile

# ---- Base image with dependencies installed for development ----
FROM base-with-deps AS base-with-deps-dev

RUN poetry install --compile --extras dev

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
    /app/poetry.lock \
    /app/entrypoint

# COPY keeps the modes of the build context, and the runtime images run as an
# unprivileged user that does not own these files: a file left group/other
# unreadable in a working copy would only fail once imported at runtime.
RUN chmod -R a+rX /app


# ---- Base runtime image ----
FROM base AS runtime-base

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

RUN mkdir -p /shared-libs/usr/lib \
    && { ldd /usr/local/bin/python3.13; \
         find /usr/local/lib/python3.13/lib-dynload /venv/lib -name '*.so*' -exec ldd {} + ; } 2>/dev/null \
       | awk '/=> \//{print $3}' | sort -u \
       | grep -Ev '^(/venv|/usr/local)/' \
       | xargs -r -I{} cp -L {} /shared-libs/usr/lib/


# ---- Python installation without pip, headers and test modules ----
FROM base AS python-stripped

RUN rm -rf \
      /usr/local/include \
      /usr/local/lib/python3.13/idlelib \
      /usr/local/lib/python3.13/lib2to3 \
      /usr/local/lib/python3.13/test \
      /usr/local/lib/python3.13/ensurepip \
      /usr/local/lib/python3.13/site-packages/pip \
      /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
      /usr/local/bin/pip* \
    && find /usr/local/lib/python3.13 -name '__pycache__' -type d -prune -exec rm -rf {} +


# ---- Distroless runtime image for production ----
# cc-debian13 provides glibc, libgcc and libstdc++; every other system library
# the interpreter and the C extensions need comes from the shared-libs stage.
# Debug with: docker run --entrypoint='' gcr.io/distroless/cc-debian13:debug-nonroot sh
FROM gcr.io/distroless/cc-debian13:nonroot AS runtime-distroless-prod
ARG DEPLOYCENTER_STATIC_ROOT=/data/static

WORKDIR /app

COPY --from=python-stripped /usr/local /usr/local
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
