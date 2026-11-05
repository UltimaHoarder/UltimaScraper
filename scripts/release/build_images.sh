#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
    cat >&2 <<'EOF'
Usage: build_images.sh VERSION [--archive] [--push REGISTRY] [--platforms LIST]
                               [--tag TAG]... [--builder NAME] [--cache REF]

Builds the release images for this host's platform: ultimascraper, the full
image that runs the backend, worker and WebUI roles, and the backend, worker and
slim webui images. Loads them into Docker as ultimascraper:VERSION and
ultimascraper-{backend,worker,webui}:VERSION and checks their runtime contracts.
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
  --archive         docker save the host-platform images to dist/.
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
export USR_BACKEND_IMAGE="${USR_BACKEND_IMAGE:-ultimascraper-backend}"
export USR_WORKER_IMAGE="${USR_WORKER_IMAGE:-ultimascraper-worker}"
export USR_WEBUI_IMAGE="${USR_WEBUI_IMAGE:-ultimascraper-webui}"
export CACHE_REF="$cache_ref"

bake=(docker buildx bake --file "$ROOT_DIR/docker-bake.hcl")
if [[ -n "$builder" ]]; then
    bake+=(--builder "$builder")
fi
host_platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"

cd "$ROOT_DIR"
"$ROOT_DIR/scripts/release/build_docker_wheelhouse.sh"
# The host-platform images under their local names, for the checks below.
REGISTRY="" PLATFORMS="$host_platform" EXTRA_TAGS="" CACHE_EXPORT="" "${bake[@]}" --load

full_ref="$USR_IMAGE:$USR_VERSION"
backend_ref="$USR_BACKEND_IMAGE:$USR_VERSION"
worker_ref="$USR_WORKER_IMAGE:$USR_VERSION"
webui_ref="$USR_WEBUI_IMAGE:$USR_VERSION"
inspect() { docker image inspect -f "$2" "$1"; }
fail() { echo "$1" >&2; exit 1; }

for image_ref in "$full_ref" "$backend_ref" "$worker_ref" "$webui_ref"; do
    image_version="$(inspect "$image_ref" '{{ index .Config.Labels "org.opencontainers.image.version" }}')"
    [[ "$image_version" == "$version" ]] || fail "Image $image_ref has version label $image_version, expected $version."
done

role() { inspect "$1" '{{range .Config.Env}}{{if eq . "USR_CONTAINER_ROLE='"$2"'"}}'"$2"'{{end}}{{end}}'; }
ports() { inspect "$1" '{{json .Config.ExposedPorts}}'; }
[[ "$(role "$full_ref" api)" == api && "$(ports "$full_ref")" == '{"21120/tcp":{},"21121/tcp":{}}' ]] \
    || fail "The full image does not default to the API role with the API and WebUI ports."
[[ "$(role "$backend_ref" api)" == api && "$(ports "$backend_ref")" == '{"21121/tcp":{}}' ]] \
    || fail "The backend image does not satisfy the API-only role/port contract."
[[ "$(role "$worker_ref" worker)" == worker && "$(ports "$worker_ref")" == null ]] \
    || fail "The worker image does not satisfy the worker-only role/port contract."
expected_identity='ultimascraper|/app|["usr-container-entrypoint"]|["ultimascraper"]'
for image_ref in "$full_ref" "$backend_ref" "$worker_ref"; do
    [[ "$(inspect "$image_ref" '{{json .Config.Healthcheck.Test}}')" == '["CMD","usr-healthcheck"]' ]] \
        || fail "Image $image_ref healthcheck contract is invalid."
    [[ "$(inspect "$image_ref" '{{.Config.User}}|{{.Config.WorkingDir}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}')" == "$expected_identity" ]] \
        || fail "Image $image_ref user/command contract is invalid."
done
[[ "$(inspect "$webui_ref" '{{json .Config.Cmd}}')" == '["ultimascraper-webui"]' ]] \
    || fail "The webui image does not start the WebUI server."
# The full image has every role's program, and its WebUI role starts the WebUI
# server with that role's defaults rather than the backend.
docker run --rm --entrypoint sh "$full_ref" -c \
    'command -v ultimascraper >/dev/null && command -v ultimascraper-webui >/dev/null && test -f /opt/webui/static/index.html' \
    || fail "The full image lacks the backend or WebUI programs or the WebUI build."
webui_start="$(docker run --rm -e USR_CONTAINER_ROLE=webui "$full_ref" sh -c 'echo "$USR_WEBUI_PORT|$USR_WEBUI_DATA_DIR"')"
[[ "$webui_start" == "21120|/data" ]] || fail "The full image's WebUI role does not start with its defaults ($webui_start)."

echo "Docker release images built: $full_ref, $backend_ref, $worker_ref, $webui_ref"

if [[ $archive -eq 1 ]]; then
    mkdir -p "$ROOT_DIR/dist"
    archive_path="$ROOT_DIR/dist/ultimascraper-docker-images-$version.tar"
    docker save --output "$archive_path" "$full_ref" "$backend_ref" "$worker_ref" "$webui_ref"
    echo "Docker image archive ready: $archive_path"
fi

if [[ -n "$registry" ]]; then
    # One image at a time: the full, backend and worker images share most layers,
    # and the Forgejo registry fails ("error writing layer blob: unknown") when the
    # same blob is uploaded twice at once. Each later image reuses the layers the
    # first one pushed.
    for target in ultimascraper backend worker webui; do
        REGISTRY="$registry" PLATFORMS="$platforms" EXTRA_TAGS="$(IFS=,; echo "${extra_tags[*]}")" CACHE_EXPORT=1 \
            "${bake[@]}" --push "$target"
    done
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
for name in ("ultimascraper", "backend", "worker", "webui"):
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
