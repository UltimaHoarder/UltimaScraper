#!/usr/bin/env bash
# Builds the installable WebUI server: the WebUI build bundled into
# ultima-scraper-webui-server. It installs ultima-scraper-core from PyPI.
#
#   scripts/release/build_webui_package.sh [OUT_DIR]   (default dist/webui-wheels)
#
# Install the result with:
#   uv tool install --find-links OUT_DIR ultima-scraper-webui-server
#
# CI publishes it so WebUIs can update themselves. It then sets:
#   USR_PACKAGE_VERSION  PEP 440 version for both wheels, e.g. 0.1.0 or
#                        0.1.0.dev20261025004224 for a build of main
#   USR_IMAGE_VERSION    the image tag built from the same commit, e.g.
#                        0.1.0-edge.0123abcd4567; recorded in the wheel so the
#                        installer suggests images that exist
# The package is then built from a temporary copy with that version.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$(realpath -m "${1:-$ROOT_DIR/dist/webui-wheels}")"
PACKAGE_DIR="$ROOT_DIR/src/UltimaScraperWeb"
WEBUI_DIR="$PACKAGE_DIR/webui"
STATIC_DIR="$PACKAGE_DIR/ultima_webui_server/static"

# npm ci would replace node_modules under a running dev server; only install when missing.
if [[ ! -d "$WEBUI_DIR/node_modules" ]]; then npm --prefix "$WEBUI_DIR" ci; fi
npm --prefix "$WEBUI_DIR" run build:production

if [[ -n "${USR_PACKAGE_VERSION:-}" ]]; then
    if [[ ! "$USR_PACKAGE_VERSION" =~ ^[0-9]+(\.[0-9]+)*((a|b|rc)[0-9]+)?(\.dev[0-9]+)?$ ]]; then
        echo "USR_PACKAGE_VERSION must be a PEP 440 version, e.g. 0.1.0 or 0.1.0.dev20261025004224." >&2
        exit 2
    fi
    STAGE_DIR="$(mktemp -d)"
    trap 'rm -rf -- "$STAGE_DIR"' EXIT
    cp -R "$PACKAGE_DIR" "$STAGE_DIR/web"
    rm -rf -- "$STAGE_DIR/web/webui" "$STAGE_DIR/web/ultima_webui_server/static"
    sed -i -E "s/^version = \"[^\"]*\"/version = \"$USR_PACKAGE_VERSION\"/" "$STAGE_DIR/web/pyproject.toml"
    printf '"""Written by scripts/release/build_webui_package.sh."""\n\nIMAGE_VERSION = %s\n' \
        "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "${USR_IMAGE_VERSION:-}")" \
        > "$STAGE_DIR/web/ultima_webui_server/_build.py"
    PACKAGE_DIR="$STAGE_DIR/web"
    STATIC_DIR="$PACKAGE_DIR/ultima_webui_server/static"
    cp -R "$WEBUI_DIR/dist" "$STATIC_DIR"
else
    rm -rf -- "$STATIC_DIR"
    cp -R "$WEBUI_DIR/dist" "$STATIC_DIR"
    trap 'rm -rf -- "$STATIC_DIR"' EXIT
fi

mkdir -p "$OUT_DIR"
uv build --wheel --out-dir "$OUT_DIR" "$PACKAGE_DIR"

wheel="$(ls -t "$OUT_DIR"/ultima_scraper_webui_server-*.whl | head -n 1)"
# The package is useless without the app it serves.
python3 - "$wheel" <<'PY'
import sys
import zipfile

names = zipfile.ZipFile(sys.argv[1]).namelist()
assert "ultima_webui_server/static/index.html" in names, "the WebUI build is missing from the wheel"
assert any(name.startswith("ultima_webui_server/installer/compose/") for name in names), "compose files are missing"
PY
echo "Built $wheel"
echo "Install: uv tool install --find-links $OUT_DIR ultima-scraper-webui-server"
