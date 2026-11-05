#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
    cat >&2 <<'EOF'
Usage: build_images.sh VERSION [--archive] [--push REGISTRY] [--platforms LIST]
                               [--tag TAG]... [--builder NAME] [--cache REF]

Builds the UltimaScraper image, which runs the backend, worker and WebUI roles,
for this host's platform, loads it into Docker as ultimascraper:VERSION and
checks its runtime contract.
VERSION is the pyproject version, or it with a prerelease suffix
(0.1.0-edge.0123abcd4567).

  --push REGISTRY   Also build every platform in --platforms and push them, e.g.
                    ghcr.io/ultimahoarder/ultimascraper. Writes
                    dist/release-manifest-VERSION.json with the pushed digests.
  --platforms LIST  Platforms to push (default linux/amd64,linux/arm64).
  --tag TAG         Extra tag to push next to VERSION; repeatable.
  --cache REF       Registry repository for the build cache, e.g.
                    REGISTRY/buildcache. Every build reads it; a push writes
                    it back, so the next build reuses unchanged layers.
  --builder NAME    Buildx builder to use. Pushing several platforms needs a
                    docker-container builder; usr-release is created if needed.
  --archive         docker save the host-platform image to dist/.
EOF
}

if [[ $# -lt 1 ]]; then
    usage
    exit 2
fi

version="$1"
shift
archive=0
registry=""
platforms="linux/amd64,linux/arm64"
builder=""
cache_ref=""
extra_tags=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --archive) archive=1; shift ;;
        --push) registry="${2:?--push needs a registry}"; shift 2 ;;
        --platforms) platforms="${2:?--platforms needs a list}"; shift 2 ;;
        --tag) extra_tags+=("${2:?--tag needs a value}"); shift 2 ;;
        --builder) builder="${2:?--builder needs a name}"; shift 2 ;;
        --cache) cache_ref="${2:?--cache needs a registry repository}"; shift 2 ;;
        *) usage; exit 2 ;;
    esac
done

if [[ ! "$version" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
    echo "VERSION must also be a valid Docker tag." >&2
    exit 2
fi

project_version="$(
    python3.14 - "$ROOT_DIR/pyproject.toml" <<'PY'
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as source:
    print(tomllib.load(source)["project"]["version"])
PY
)"
# A release is the project version; a prerelease adds a suffix to it, e.g.
# 0.1.0-edge.0123abcd4567 for an image built from main.
if [[ "$version" != "$project_version" && "$version" != "$project_version"-* ]]; then
    echo "Image version $version does not match project version $project_version (or $project_version-SUFFIX)." >&2
    exit 1
fi

if [[ -n "$registry" && -z "$builder" ]]; then
    builder=usr-release
    if ! docker buildx inspect "$builder" >/dev/null 2>&1; then
        docker buildx create --name "$builder" --driver docker-container --bootstrap >/dev/null
    fi
fi

export USR_VERSION="$version"
export USR_REQUIRE_WHEELHOUSE=1
export USR_REVISION="${USR_REVISION:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
export USR_IMAGE="${USR_IMAGE:-ultimascraper}"
export CACHE_REF="$cache_ref"

bake=(docker buildx bake --file "$ROOT_DIR/docker-bake.hcl")
if [[ -n "$builder" ]]; then
    bake+=(--builder "$builder")
fi
host_platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"

cd "$ROOT_DIR"
"$ROOT_DIR/scripts/release/build_docker_wheelhouse.sh"
# The host-platform image under its local name, for the checks below.
REGISTRY="" PLATFORMS="$host_platform" EXTRA_TAGS="" CACHE_EXPORT="" "${bake[@]}" --load

image_ref="$USR_IMAGE:$USR_VERSION"
inspect() { docker image inspect -f "$1" "$image_ref"; }

image_version="$(inspect '{{ index .Config.Labels "org.opencontainers.image.version" }}')"
if [[ "$image_version" != "$version" ]]; then
    echo "Image $image_ref has version label $image_version, expected $version." >&2
    exit 1
fi
default_role="$(inspect '{{range .Config.Env}}{{if eq . "USR_CONTAINER_ROLE=api"}}api{{end}}{{end}}')"
if [[ "$default_role" != api || "$(inspect '{{json .Config.ExposedPorts}}')" != '{"21120/tcp":{},"21121/tcp":{}}' ]]; then
    echo "Image does not default to the API role with the API and WebUI ports." >&2
    exit 1
fi
if [[ "$(inspect '{{json .Config.Healthcheck.Test}}')" != '["CMD","usr-healthcheck"]' ]]; then
    echo "Image healthcheck contract is invalid." >&2
    exit 1
fi
expected_identity='ultimascraper|/app|["usr-container-entrypoint"]|["ultimascraper"]'
if [[ "$(inspect '{{.Config.User}}|{{.Config.WorkingDir}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}')" != "$expected_identity" ]]; then
    echo "Image user/command contract is invalid." >&2
    exit 1
fi
# Every role's program is there, and the WebUI role starts the WebUI server
# with its own defaults rather than the backend.
docker run --rm --entrypoint sh "$image_ref" -c \
    'command -v ultimascraper >/dev/null && command -v ultimascraper-webui >/dev/null && test -f /opt/webui/static/index.html' \
    || { echo "Image lacks the backend or WebUI programs or the WebUI build." >&2; exit 1; }
webui_start="$(docker run --rm -e USR_CONTAINER_ROLE=webui "$image_ref" sh -c 'echo "$USR_WEBUI_PORT|$USR_WEBUI_DATA_DIR"')"
if [[ "$webui_start" != "21120|/data" ]]; then
    echo "The WebUI role does not start with its defaults ($webui_start)." >&2
    exit 1
fi

echo "Docker release image built: $image_ref"

if [[ $archive -eq 1 ]]; then
    mkdir -p "$ROOT_DIR/dist"
    archive_path="$ROOT_DIR/dist/ultimascraper-docker-images-$version.tar"
    docker save --output "$archive_path" "$image_ref"
    echo "Docker image archive ready: $archive_path"
fi

if [[ -n "$registry" ]]; then
    REGISTRY="$registry" PLATFORMS="$platforms" EXTRA_TAGS="$(IFS=,; echo "${extra_tags[*]}")" CACHE_EXPORT=1 \
        "${bake[@]}" --push ultimascraper
    mkdir -p "$ROOT_DIR/dist"
    manifest_path="$ROOT_DIR/dist/release-manifest-$version.json"
    # Each pushed tag must be an index holding every requested platform; the
    # manifest records the immutable digests deployments should pin.
    python3.14 - "$registry" "$version" "$platforms" "$USR_REVISION" "$manifest_path" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

registry, version, platforms, revision, manifest_path = sys.argv[1:]
expected = set(platforms.split(","))
images = {}
for name in ("ultimascraper",):
    ref = f"{registry}/{name}:{version}"
    raw = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", "--raw", ref],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    index = json.loads(raw)
    found = {
        "/".join(filter(None, (p.get("os"), p.get("architecture"), p.get("variant"))))
        for entry in index.get("manifests", [])
        if (p := entry.get("platform", {})).get("os") not in (None, "unknown")
    }
    # arm64 is reported with its v8 variant.
    found_short = {platform.removesuffix("/v8") for platform in found}
    missing = expected - found_short
    if missing:
        raise SystemExit(f"{ref} is missing platforms: {', '.join(sorted(missing))}")
    images[name] = {
        "reference": ref,
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "platforms": sorted(found_short),
    }
Path(manifest_path).write_text(
    json.dumps({"version": version, "revision": revision, "images": images}, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Release manifest written: {manifest_path}")
PY
fi
