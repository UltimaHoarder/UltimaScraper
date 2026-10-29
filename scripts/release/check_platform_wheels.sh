#!/usr/bin/env bash
# Fail when a locked dependency ships a wheel for one image platform but only
# source for another. That package would be compiled during the image build,
# which takes hours under QEMU. Packages that are source-only everywhere (pure
# Python ones such as construct) are listed but allowed.
#
# Usage: check_platform_wheels.sh [ARCH]...   (default: x86_64 aarch64)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCK="$ROOT_DIR/docker/requirements.lock"
architectures=("$@")
if [[ ${#architectures[@]} -eq 0 ]]; then
    architectures=(x86_64 aarch64)
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Version-control requirements are pure-Python sources installed at build time.
grep -v -E '^\s*(#|$)|@ git\+' "$LOCK" > "$work/requirements.txt"

for arch in "${architectures[@]}"; do
    platforms=()
    # The images use Debian trixie (glibc 2.41); any of these manylinux tags fit.
    for glibc in 2014 _2_17 _2_28 _2_31 _2_34 _2_35 _2_36 _2_38 _2_39; do
        platforms+=(--platform "manylinux${glibc}_${arch}")
    done
    echo "Resolving wheels for $arch"
    python3.14 -m pip download \
        --quiet \
        --disable-pip-version-check \
        --no-deps \
        --prefer-binary \
        --implementation cp \
        --python-version 3.14 \
        "${platforms[@]}" \
        --dest "$work/$arch" \
        --requirement "$work/requirements.txt"
done

python3.14 - "$work" "${architectures[@]}" <<'PY'
import re
import sys
from pathlib import Path

work, *architectures = sys.argv[1:]


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sources(arch: str) -> set[str]:
    found = set()
    for path in (Path(work) / arch).iterdir():
        if path.suffix != ".whl":
            # name-version.tar.gz / .zip
            found.add(normalise(path.name.rsplit("-", 1)[0]))
    return found


per_arch = {arch: sources(arch) for arch in architectures}
everywhere = set.intersection(*per_arch.values())
problems = {arch: names - everywhere for arch, names in per_arch.items() if names - everywhere}
if everywhere:
    print("Source-only on every platform (built at image build time):", ", ".join(sorted(everywhere)))
for arch, names in problems.items():
    print(f"No {arch} wheel, although another platform has one: {', '.join(sorted(names))}")
if problems:
    raise SystemExit(1)
print("Every locked dependency resolves the same way on:", ", ".join(architectures))
PY
