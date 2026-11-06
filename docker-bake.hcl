# The release images for every supported architecture: the full ultimascraper
# image, which runs every role (USR_CONTAINER_ROLE picks one per container), and
# the backend, worker and slim webui images for those who want one role each.
#
# Local, host-platform build loaded into Docker (what build_images.sh does first):
#   docker buildx bake --load --set '*.platform=linux/amd64'
# Release, all platforms, pushed to ghcr.io:
#   REGISTRY=ghcr.io/ultimahoarder/ultimascraper USR_VERSION=0.1.0 \
#     docker buildx bake --push
# A multi-platform build needs a docker-container builder and, on an amd64 host,
# QEMU registered for arm64 (see docs/operations/docker.md).

variable "REGISTRY" {
  # Empty: local names that docker-compose.yml uses by default.
  default = ""
}

variable "USR_VERSION" {
  default = "dev"
}

variable "EXTRA_TAGS" {
  # Comma-separated tags added next to USR_VERSION, e.g. "0.1,latest,sha-0123abcd".
  default = ""
}

variable "CACHE_REF" {
  # Registry repository for the build cache, e.g.
  # ghcr.io/ultimahoarder/ultimascraper/buildcache; empty builds without one.
  # Each image keeps its cache under its own tag (buildcache:ultimascraper, ...).
  default = ""
}

variable "CACHE_EXPORT" {
  # "1" also writes the cache back; otherwise it is only read.
  default = ""
}

variable "PLATFORMS" {
  default = "linux/amd64,linux/arm64"
}

variable "USR_REQUIRE_WHEELHOUSE" {
  default = "1"
}

variable "USR_REVISION" {
  default = "unknown"
}

variable "USR_BACKEND_REVISION" {
  default = "unknown"
}

variable "USR_API_REVISION" {
  default = "unknown"
}

variable "USDB_REVISION" {
  default = "unknown"
}

variable "USDB_ARCHIVE_REVISION" {
  default = "unknown"
}

variable "USR_CORE_REVISION" {
  default = "unknown"
}

function "image" {
  params = [name]
  # Local names: ultimascraper, and ultimascraper-backend etc. for the others.
  result = REGISTRY == "" ? (name == "ultimascraper" ? name : "ultimascraper-${name}") : "${REGISTRY}/${name}"
}

function "tags" {
  params = [name]
  result = concat(
    ["${image(name)}:${USR_VERSION}"],
    [for tag in compact(split(",", EXTRA_TAGS)) : "${image(name)}:${tag}"],
  )
}

function "cache_from" {
  params = [name]
  result = CACHE_REF == "" ? [] : ["type=registry,ref=${CACHE_REF}:${name}"]
}

function "cache_to" {
  params = [name]
  # mode=max keeps the dependency stages too, which is what makes them reusable.
  result = CACHE_REF == "" || CACHE_EXPORT != "1" ? [] : [
    "type=registry,ref=${CACHE_REF}:${name},mode=max,image-manifest=true,oci-mediatypes=true",
  ]
}

group "default" {
  targets = ["ultimascraper", "backend", "worker", "webui"]
}

target "_release" {
  platforms = split(",", PLATFORMS)
}

target "_python" {
  inherits   = ["_release"]
  context    = "."
  dockerfile = "Dockerfile"
  args = {
    USR_REQUIRE_WHEELHOUSE = USR_REQUIRE_WHEELHOUSE
    USR_VERSION            = USR_VERSION
    USR_REVISION           = USR_REVISION
    USR_BACKEND_REVISION   = USR_BACKEND_REVISION
    USR_API_REVISION       = USR_API_REVISION
    USDB_REVISION          = USDB_REVISION
    USDB_ARCHIVE_REVISION  = USDB_ARCHIVE_REVISION
    USR_CORE_REVISION      = USR_CORE_REVISION
  }
}

target "ultimascraper" {
  inherits   = ["_python"]
  target     = "runtime"
  tags       = tags("ultimascraper")
  cache-from = cache_from("ultimascraper")
  cache-to   = cache_to("ultimascraper")
}

target "backend" {
  inherits   = ["_python"]
  target     = "backend"
  tags       = tags("backend")
  cache-from = cache_from("backend")
  cache-to   = cache_to("backend")
}

target "worker" {
  inherits   = ["_python"]
  target     = "worker"
  tags       = tags("worker")
  cache-from = cache_from("worker")
  cache-to   = cache_to("worker")
}

target "webui" {
  inherits   = ["_release"]
  # The WebUI and its server live in src/UltimaScraperWeb, so the context is the repository root.
  context    = "."
  dockerfile = "src/UltimaScraperWeb/webui/Dockerfile"
  args = {
    USR_VERSION = USR_VERSION
  }
  tags       = tags("webui")
  cache-from = cache_from("webui")
  cache-to   = cache_to("webui")
}
