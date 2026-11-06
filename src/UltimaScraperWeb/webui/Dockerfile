# syntax=docker/dockerfile:1
# Built from the repository root (it needs src/), with the allow-list in
# src/UltimaScraperWeb/webui/Dockerfile.dockerignore.

# Multi-arch indexes (amd64, arm64 and more), pinned so every platform builds the same release.
# The bundle is plain static files, so it is built once on the build host's own
# platform instead of under emulation for each target.
FROM --platform=$BUILDPLATFORM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS assets

WORKDIR /build

COPY src/UltimaScraperWeb/webui/package.json src/UltimaScraperWeb/webui/package-lock.json ./
RUN npm ci

COPY src/UltimaScraperWeb/webui/ .
RUN npm run build:production

FROM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS server-deps-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependencies first: reused until the lock file changes.
COPY docker/webui-requirements.lock /webui-requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --requirement /webui-requirements.lock

# The same steps on the build host's own platform (--platform only takes effect
# on an image, not on a stage name). Identical to the stage above when the
# target is the build platform, so BuildKit runs them once.
FROM --platform=$BUILDPLATFORM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS server-deps-builder-native

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependencies first: reused until the lock file changes.
COPY docker/webui-requirements.lock /webui-requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --requirement /webui-requirements.lock

# The server and ultima-scraper-core are pure Python: installed once on the
# build host's own platform into /opt/overlay (laid out as in /opt/venv) and
# copied into every image, so arm64 does not run this under emulation. A
# release takes core from the prebuilt wheelhouse; without one, from PyPI.
FROM server-deps-builder-native AS server-app-builder

COPY docker/wheelhouse /wheelhouse
COPY src/UltimaScraperWeb/pyproject.toml src/UltimaScraperWeb/README.md /src/UltimaScraperWeb/
COPY src/UltimaScraperWeb/ultima_webui_server /src/UltimaScraperWeb/ultima_webui_server

RUN site="$(/opt/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && overlay="/opt/overlay$site" \
    && core="$(find /wheelhouse -maxdepth 1 -name 'ultima_scraper_core-*.whl' | head -n 1)" \
    && /opt/venv/bin/pip install --no-deps --target "$overlay" "${core:-ultima-scraper-core>=0.1,<1}" /src/UltimaScraperWeb \
    && mkdir -p /opt/overlay/opt/venv \
    && mv "$overlay/bin" /opt/overlay/opt/venv/bin \
    && PYTHONPATH="$overlay" /opt/venv/bin/pip check

FROM server-deps-builder AS server-deps

RUN /opt/venv/bin/pip uninstall --yes pip

FROM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    USR_WEBUI_HOST=0.0.0.0 \
    USR_WEBUI_PORT=21120 \
    USR_WEBUI_DATA_DIR=/data \
    USR_WEBUI_STATIC_DIR=/opt/webui/static

# uid 1000 matches the backend image, so the backend's config volume (and its
# generated admin token) can be mounted read-only here.
RUN python -m pip uninstall --yes pip \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin ultimascraper \
    && mkdir -p /data \
    && chown ultimascraper:ultimascraper /data

COPY --from=server-deps /opt/venv /opt/venv
COPY --from=server-app-builder /opt/overlay/ /
COPY --from=assets /build/dist /opt/webui/static

# Declared after the RUN steps: a changing version must not rebuild them.
ARG USR_VERSION=dev

LABEL org.opencontainers.image.title="UltimaScraper WebUI" \
    org.opencontainers.image.description="WebUI server: the app, sign-in, and proxies to UltimaScraper backends" \
    org.opencontainers.image.version="${USR_VERSION}" \
    org.opencontainers.image.source="https://github.com/UltimaHoarder/UltimaScraper" \
    org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENV USR_WEBUI_VERSION="${USR_VERSION}"

USER ultimascraper

EXPOSE 21120

# HTTP or HTTPS, as USR_WEBUI_TLS* configure it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-m", "ultima_webui_server.healthcheck"]

CMD ["ultimascraper-webui"]
