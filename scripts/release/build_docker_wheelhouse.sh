#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_DIR="$(dirname "$ROOT_DIR")"
OUTPUT_DIR="$ROOT_DIR/docker/wheelhouse"

declare -a PROJECTS=(
  "$WORKSPACE_DIR/UltimaScraperAPI"
  "$WORKSPACE_DIR/UltimaDatabases/UltimaScraperDB"
  "$WORKSPACE_DIR/UltimaScraperCore"
  "$WORKSPACE_DIR/UltimaDatabases/UltimaScraperDBArchive"
  "$WORKSPACE_DIR/UltimaBackends/UltimaScraperBackend"
)

for project_dir in "${PROJECTS[@]}"; do
  if [[ ! -f "$project_dir/pyproject.toml" ]]; then
    echo "Missing release source: $project_dir" >&2
    exit 1
  fi
done

mkdir -p "$OUTPUT_DIR"
find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*.whl' -delete

for project_dir in "${PROJECTS[@]}"; do
  echo "Building $(basename "$project_dir")"
  uv build \
    --wheel \
    --python 3.14 \
    --no-sources \
    --out-dir "$OUTPUT_DIR" \
    "$project_dir"
done

echo "Docker release wheelhouse ready: $OUTPUT_DIR"
