#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
    cat >&2 <<'EOF'
Usage: build_images.sh VERSION [--archive] [--push REGISTRY] [--platforms LIST]
                               [--tag TAG]... [--builder NAME] [--cache REF]

Builds the backend, worker and WebUI images for this host's platform, loads
them into Docker as ultimascraper-*:VERSION and checks their runtime contracts.
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
# Host-platform images under the local names, for the checks below.
REGISTRY="" PLATFORMS="$host_platform" EXTRA_TAGS="" CACHE_EXPORT="" "${bake[@]}" --load

backend_ref="$USR_BACKEND_IMAGE:$USR_VERSION"
worker_ref="$USR_WORKER_IMAGE:$USR_VERSION"
webui_ref="$USR_WEBUI_IMAGE:$USR_VERSION"

for image_ref in "$backend_ref" "$worker_ref" "$webui_ref"; do
    image_version="$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$image_ref")"
    if [[ "$image_version" != "$version" ]]; then
        echo "Image $image_ref has version label $image_version, expected $version." >&2
        exit 1
    fi
done

backend_role="$(docker image inspect -f '{{range .Config.Env}}{{if eq . "USR_CONTAINER_ROLE=api"}}api{{end}}{{end}}' "$backend_ref")"
worker_role="$(docker image inspect -f '{{range .Config.Env}}{{if eq . "USR_CONTAINER_ROLE=worker"}}worker{{end}}{{end}}' "$worker_ref")"
backend_ports="$(docker image inspect -f '{{json .Config.ExposedPorts}}' "$backend_ref")"
worker_ports="$(docker image inspect -f '{{json .Config.ExposedPorts}}' "$worker_ref")"
backend_health="$(docker image inspect -f '{{json .Config.Healthcheck.Test}}' "$backend_ref")"
worker_health="$(docker image inspect -f '{{json .Config.Healthcheck.Test}}' "$worker_ref")"
backend_identity="$(docker image inspect -f '{{.Config.User}}|{{.Config.WorkingDir}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}' "$backend_ref")"
worker_identity="$(docker image inspect -f '{{.Config.User}}|{{.Config.WorkingDir}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}' "$worker_ref")"

if [[ "$backend_role" != api || "$backend_ports" != '{"21121/tcp":{}}' ]]; then
    echo "Backend image does not satisfy the API-only role/port contract." >&2
    exit 1
fi
if [[ "$worker_role" != worker || "$worker_ports" != null ]]; then
    echo "Worker image does not satisfy the worker-only role/port contract." >&2
    exit 1
fi
if [[ "$backend_health" == null || "$worker_health" != '["CMD","python","/usr/local/bin/usr-worker-healthcheck"]' ]]; then
    echo "Backend or worker image healthcheck contract is invalid." >&2
    exit 1
fi
expected_identity='ultimascraper|/app|["usr-container-entrypoint"]|["ultimascraper"]'
if [[ "$backend_identity" != "$expected_identity" || "$worker_identity" != "$expected_identity" ]]; then
    echo "Backend or worker image user/command contract is invalid." >&2
    exit 1
fi

echo "Docker release images built: $backend_ref, $worker_ref, $webui_ref"

if [[ $archive -eq 1 ]]; then
    mkdir -p "$ROOT_DIR/dist"
    archive_path="$ROOT_DIR/dist/ultimascraper-docker-images-$version.tar"
    docker save --output "$archive_path" "$backend_ref" "$worker_ref" "$webui_ref"
    echo "Docker image archive ready: $archive_path"
fi

if [[ -n "$registry" ]]; then
    # One image at a time: backend and worker share most layers, and the Forgejo
    # registry fails ("error writing layer blob: unknown") when the same blob is
    # uploaded twice at once, which a parallel cache export does. The worker
    # then reuses the layers the backend just built.
    for target in backend worker webui; do
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
for name in ("backend", "worker", "webui"):
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
