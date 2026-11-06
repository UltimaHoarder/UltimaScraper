# The full image, ultimascraper (the last stage, runtime), runs every
# UltimaScraper role: the API, the scrape workers and the WebUI server.
# USR_CONTAINER_ROLE (api, worker or webui) picks the one a container runs;
# unset, a container with no database or Redis settings runs the WebUI, and
# any other the API. The backend and worker stages are the same build with
# their role, ports and healthcheck fixed; the slim WebUI-only image is
# src/UltimaScraperWeb/webui/Dockerfile.
#
# Layers are ordered so a release rebuilds as little as possible: the system
# packages and the third-party dependencies only change with the base image or
# docker/requirements.lock, and a build's own code (first-party wheels and
# main.py) lands in a small layer of its own. Version arguments are declared
# after the heavy steps, because a build argument used by a RUN step makes
# that step miss the cache whenever its value changes.

FROM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS deps-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Third-party dependencies only: reused until the lock file changes.
COPY docker/requirements.lock /requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install setuptools==84.0.0 wheel==0.48.0 \
    && /opt/venv/bin/pip install --requirement /requirements.lock

# The same steps on the build host's own platform. --platform only takes effect
# on an image, not on a stage name, so the stage is repeated; when the target
# is the build platform the steps are identical and BuildKit runs them once.
FROM --platform=$BUILDPLATFORM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS deps-builder-native

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Third-party dependencies only: reused until the lock file changes.
COPY docker/requirements.lock /requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install setuptools==84.0.0 wheel==0.48.0 \
    && /opt/venv/bin/pip install --requirement /requirements.lock

# The first-party packages are pure Python, so they are installed once on the
# build host's own platform and copied into every image: an arm64 build no
# longer runs this step under emulation. The site-packages path and the
# /opt/venv/bin/python shebang are the same on every platform.
FROM deps-builder-native AS app-builder

ARG USR_REQUIRE_WHEELHOUSE=0

WORKDIR /build

# A maintainer may prebuild first-party wheels from the release-day source
# checkouts. End users never need those sibling repositories: only wheel
# artifacts are consumed, and published distributions remain a valid fallback.
COPY docker/wheelhouse /wheelhouse
COPY pyproject.toml README.md ./
COPY main.py ./main.py
COPY src/UltimaScraperWeb/pyproject.toml src/UltimaScraperWeb/README.md ./web/
COPY src/UltimaScraperWeb/ultima_webui_server ./web/ultima_webui_server

# The first-party packages go into /opt/overlay, laid out as they belong in
# /opt/venv, so the runtime copies them over the dependencies as one small layer.
RUN site="$(/opt/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && overlay="/opt/overlay$site" \
    && wheel_count="$(find /wheelhouse -maxdepth 1 -type f -name '*.whl' | wc -l)" \
    && if [ "$wheel_count" -gt 0 ]; then \
        test "$wheel_count" -eq 5; \
        /opt/venv/bin/pip install --no-deps --target "$overlay" /wheelhouse/*.whl . ./web; \
    else \
        test "$USR_REQUIRE_WHEELHOUSE" = 0; \
        /opt/venv/bin/pip install --target "$overlay" . ./web; \
    fi \
    && mkdir -p /opt/overlay/opt/venv \
    && mv "$overlay/bin" /opt/overlay/opt/venv/bin \
    && PYTHONPATH="$overlay" /opt/venv/bin/pip check

# The WebUI is plain static files, so it is built once on the build host's own
# platform instead of under emulation for each target.
FROM --platform=$BUILDPLATFORM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS webui-assets

WORKDIR /build

COPY src/UltimaScraperWeb/webui/package.json src/UltimaScraperWeb/webui/package-lock.json ./
RUN npm ci

COPY src/UltimaScraperWeb/webui/ .
RUN npm run build:production

FROM deps-builder AS deps

# The runtime venv carries no installer, as before.
RUN /opt/venv/bin/pip uninstall --yes pip setuptools wheel

# Bento4's mp4decrypt and mp4dump, which DRM downloads need. Debian packages
# neither, and Bento4 publishes x86-only binaries, so they are built from a
# pinned release for each target platform (arm64 included).
FROM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS bento4-builder

ARG BENTO4_VERSION=1.6.0-641
ARG BENTO4_SHA256=e6575877708526e399cff752b4ee23cb1e2ac32fb251e2ca0a1e8d691fd172a7

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates cmake curl g++ make \
    && curl -fsSL -o /tmp/bento4.tar.gz \
        "https://github.com/axiomatic-systems/Bento4/archive/refs/tags/v${BENTO4_VERSION}.tar.gz" \
    && echo "${BENTO4_SHA256}  /tmp/bento4.tar.gz" | sha256sum -c - \
    && mkdir /tmp/bento4 \
    && tar -xzf /tmp/bento4.tar.gz -C /tmp/bento4 --strip-components=1 \
    && cmake -S /tmp/bento4 -B /tmp/bento4/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/bento4/build --target mp4decrypt mp4dump -j"$(nproc)" \
    && install -D -m 0755 /tmp/bento4/build/mp4decrypt /opt/bento4/mp4decrypt \
    && install -D -m 0755 /tmp/bento4/build/mp4dump /opt/bento4/mp4dump

FROM python:3.14.7-slim-trixie@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS runtime-base

# Bento4 first: pymp4 installs an unrelated mp4dump into /opt/venv/bin, and
# OnlyDRM finds its tools on PATH.
ENV PATH="/opt/bento4/bin:/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    USR_LOG_DIR=/app/logs \
    USR_PLUGINS_DIR=/app/__user_data__/plugins

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg libpq5 libssl3t64 openssl openssl-provider-legacy \
    && python -m pip uninstall --yes pip \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin ultimascraper \
    && mkdir -p /app/logs /app/__user_data__/plugins /home/ultimascraper/.config/ultima_scraper_verse /data \
    && chown -R ultimascraper:ultimascraper /app /home/ultimascraper /data

COPY --from=bento4-builder /opt/bento4/ /opt/bento4/bin/
COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
COPY docker/backend-entrypoint.sh /usr/local/bin/usr-container-entrypoint
COPY docker/healthcheck.sh /usr/local/bin/usr-healthcheck
COPY docker/worker-healthcheck.py /usr/local/bin/usr-worker-healthcheck

RUN chmod 0755 \
        /usr/local/bin/usr-container-entrypoint \
        /usr/local/bin/usr-healthcheck \
        /usr/local/bin/usr-worker-healthcheck

COPY --from=webui-assets /build/dist /opt/webui/static

# This build's own code, over the dependencies.
COPY --from=app-builder /opt/overlay/ /

ARG USR_VERSION=dev
ARG USR_REVISION=unknown
ARG USR_BACKEND_REVISION=unknown
ARG USR_API_REVISION=unknown
ARG USDB_REVISION=unknown
ARG USDB_ARCHIVE_REVISION=unknown
ARG USR_CORE_REVISION=unknown

# The release this image is, as the backend, workers and WebUI report it (e.g. 0.1.0-edge.0123abcd4567).
ENV USR_IMAGE_VERSION="${USR_VERSION}" \
    USR_WEBUI_VERSION="${USR_VERSION}"

LABEL org.opencontainers.image.title="UltimaScraper" \
    org.opencontainers.image.description="UltimaScraper's API, scrape workers and WebUI; USR_CONTAINER_ROLE picks one" \
    org.opencontainers.image.version="${USR_VERSION}" \
    org.opencontainers.image.revision="${USR_REVISION}" \
    org.opencontainers.image.source="https://github.com/UltimaHoarder/UltimaScraper" \
    org.ultimascraper.backend.revision="${USR_BACKEND_REVISION}" \
    org.ultimascraper.api.revision="${USR_API_REVISION}" \
    org.ultimascraper.usdb.revision="${USDB_REVISION}" \
    org.ultimascraper.usdb-archive.revision="${USDB_ARCHIVE_REVISION}" \
    org.ultimascraper.core.revision="${USR_CORE_REVISION}" \
    org.opencontainers.image.licenses="AGPL-3.0-or-later"

USER ultimascraper

ENTRYPOINT ["usr-container-entrypoint"]
CMD ["ultimascraper"]

# The backend image: the API role only.
FROM runtime-base AS backend

LABEL org.opencontainers.image.title="UltimaScraper backend" \
    org.opencontainers.image.description="UltimaScraper's API control plane"

ENV USR_CONTAINER_ROLE=api

EXPOSE 21121

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD ["usr-healthcheck"]

# The worker image: scrape workers only; it listens on no port.
FROM runtime-base AS worker

LABEL org.opencontainers.image.title="UltimaScraper worker" \
    org.opencontainers.image.description="UltimaScraper's scrape and download workers"

ENV USR_CONTAINER_ROLE=worker

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD ["usr-healthcheck"]

# The full image, last so a plain docker build makes it. The role's own
# defaults (ports, bind address, data folders) are set by the entrypoint, so
# each role starts as its own image does.
FROM runtime-base AS runtime

# The API listens on 21121 and the WebUI on 21120; a worker listens on neither.
EXPOSE 21121 21120

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD ["usr-healthcheck"]
