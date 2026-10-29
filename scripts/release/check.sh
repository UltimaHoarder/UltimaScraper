#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DOCKER=0

if [[ $# -gt 1 || (${1:-} != "" && ${1:-} != "--docker") ]]; then
    echo "Usage: $0 [--docker]" >&2
    exit 2
fi
if [[ ${1:-} == "--docker" ]]; then
    RUN_DOCKER=1
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/usr-release-uv-cache}"

cd "$ROOT_DIR"

python_minor="$(python3.14 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_minor" != "3.14" ]]; then
    echo "The release gate requires Python 3.14." >&2
    exit 1
fi

uv lock --check --python 3.14
uv sync --frozen --python 3.14 --group dev --group docs

echo "== Backend tests (plugins included) =="
release_check_config_dir="$(mktemp -d "${TMPDIR:-/tmp}/usr-release-check.XXXXXX")"
trap 'rm -rf -- "$release_check_config_dir"' EXIT
release_check_db_url="postgresql+psycopg://release-check:release-check@127.0.0.1:1/unavailable"
env \
    -u ONLYFANS_DATABASE_URL \
    -u FANSLY_DATABASE_URL \
    -u LOYALFANS_DATABASE_URL \
    -u REDIS_URL \
    -u REDIS_HOST \
    -u REDIS_PORT \
    -u REDIS_PASSWORD \
    -u DATABASE_URL \
    ULTIMA_ARCHIVE_DATABASE_URL="$release_check_db_url" \
    XDG_CONFIG_HOME="$release_check_config_dir" \
    USR_PLUGINS_DIR="$release_check_config_dir/plugins" \
    "$ROOT_DIR/.venv/bin/python" -m pytest -q

echo "== Import boundaries =="
"$ROOT_DIR/.venv/bin/python" scripts/dev/check_import_boundaries.py

echo "== WebUI =="
(
    cd src/UltimaScraperWeb/webui
    npm ci
    npm audit --omit=dev --audit-level=high
    npm run lint
    npm run typecheck:tests
    npm run test:unit
    npm run build:production
    npm run test:smoke
)

echo "== Documentation =="
"$ROOT_DIR/.venv/bin/zensical" build --strict

echo "== Distribution artifacts =="
"$ROOT_DIR/scripts/release/build_artifacts.sh"

if [[ $RUN_DOCKER -eq 1 ]]; then
    echo "== Isolated Docker acceptance =="
    "$ROOT_DIR/scripts/release/docker_acceptance.sh"
fi

echo "Release checks passed."
