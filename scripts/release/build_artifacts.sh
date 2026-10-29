#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
VERIFY_DIR=""
PYTHON_BIN="$(python3.14 -c 'from pathlib import Path; import sys; print(Path(sys.executable).resolve())')"

cleanup() {
    if [[ -n "$VERIFY_DIR" && -d "$VERIFY_DIR" ]]; then
        rm -rf -- "$VERIFY_DIR"
    fi
}
trap cleanup EXIT

cd "$ROOT_DIR"

python_minor="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_minor" != "3.14" ]]; then
    echo "Release artifacts must be built with Python 3.14." >&2
    exit 1
fi

uv lock --check --python 3.14
"$ROOT_DIR/scripts/release/build_docker_wheelhouse.sh"

project_version="$(
    "$PYTHON_BIN" - "$ROOT_DIR/pyproject.toml" <<'PY'
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as source:
    print(tomllib.load(source)["project"]["version"])
PY
)"

uv build \
    --sdist \
    --clear \
    --python 3.14 \
    --no-sources \
    --out-dir "$DIST_DIR" \
    "$ROOT_DIR"

source_archives=("$DIST_DIR"/ultimascraper-*.tar.gz)
if [[ ${#source_archives[@]} -ne 1 || ! -f "${source_archives[0]}" ]]; then
    echo "Expected exactly one USR source distribution." >&2
    exit 1
fi

uv build \
    --wheel \
    --python 3.14 \
    --no-sources \
    --out-dir "$DIST_DIR" \
    "${source_archives[0]}"

root_wheels=("$DIST_DIR"/ultimascraper-*.whl)
if [[ ${#root_wheels[@]} -ne 1 || ! -f "${root_wheels[0]}" ]]; then
    echo "Expected exactly one USR wheel." >&2
    exit 1
fi

"$PYTHON_BIN" - "${root_wheels[0]}" <<'PY'
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

wheel_path = Path(sys.argv[1])
with zipfile.ZipFile(wheel_path) as wheel:
    files = set(wheel.namelist())

required = {"main.py"}
missing = required - files
forbidden = [
    name
    for name in files
    if "_archive/" in name
    or name.startswith("ultima_scraper_backend/")
    or name.startswith("UltimaScraperDBArchive/")
    or name.startswith("UltimaScraperCore/")
]
if missing or forbidden:
    raise SystemExit(
        f"Invalid root wheel contents: missing={sorted(missing)} "
        f"forbidden={sorted(forbidden)[:10]}"
    )
PY

mkdir -p "$DIST_DIR/wheelhouse"
install -m 0644 "$ROOT_DIR"/docker/wheelhouse/*.whl "$DIST_DIR/wheelhouse/"
install -m 0644 "${root_wheels[0]}" "$DIST_DIR/wheelhouse/"
install -m 0644 "$ROOT_DIR/docker/requirements.lock" "$DIST_DIR/wheelhouse/"

release_wheels=("$DIST_DIR"/wheelhouse/*.whl)
if [[ ${#release_wheels[@]} -ne 6 ]]; then
    echo "Expected five first-party dependency wheels and one USR wheel." >&2
    exit 1
fi

# Verify a consumer install from outside the repository. First-party packages
# are installed only from the built wheelhouse, so editable siblings cannot
# hide a packaging defect.
VERIFY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/usr-wheel-verify.XXXXXXXX")"
"$PYTHON_BIN" -m venv "$VERIFY_DIR/venv"
"$VERIFY_DIR/venv/bin/pip" install \
    --disable-pip-version-check \
    --requirement "$ROOT_DIR/docker/requirements.lock"
"$VERIFY_DIR/venv/bin/pip" install \
    --disable-pip-version-check \
    --no-deps \
    "${release_wheels[@]}"
"$VERIFY_DIR/venv/bin/pip" check
(
    cd "$VERIFY_DIR"
    "$VERIFY_DIR/venv/bin/python" - <<'PY'
from __future__ import annotations

import sys

import main
import packaging
import ultima_scraper_api
import ultima_scraper_backend
import ultima_scraper_core
import ultima_scraper_db
import ultima_scraper_db_archive
from ultima_scraper_backend.plugin_system.platform import PluginPlatform

assert sys.version_info[:2] == (3, 14)
for module in (
    main,
    packaging,
    ultima_scraper_api,
    ultima_scraper_backend,
    ultima_scraper_core,
    ultima_scraper_db,
    ultima_scraper_db_archive,
):
    assert "/venv/" in str(module.__file__), module.__file__
assert PluginPlatform.__module__ == "ultima_scraper_backend.plugin_system.platform"
PY
)

bundle_name="ultimascraper-docker-$project_version"
bundle_parent="$DIST_DIR/docker"
bundle_dir="$bundle_parent/$bundle_name"
mkdir -p "$bundle_dir"
install -m 0644 "$ROOT_DIR/docker-compose.yml" "$bundle_dir/docker-compose.yml"
install -m 0644 "$ROOT_DIR/docker/RELEASE_README.md" "$bundle_dir/README.md"
install -m 0644 "$ROOT_DIR/LICENSE" "$bundle_dir/LICENSE"
install -m 0644 "$ROOT_DIR/SECURITY.md" "$bundle_dir/SECURITY.md"
sed "s/^# USR_VERSION=dev$/USR_VERSION=$project_version/" \
    "$ROOT_DIR/.env.example" >"$bundle_dir/.env.example"
tar -C "$bundle_parent" -czf \
    "$DIST_DIR/ultimascraper-docker-compose-$project_version.tar.gz" \
    "$bundle_name"

echo "Release artifacts ready in $DIST_DIR"
