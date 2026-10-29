#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

CHECKS: list[tuple[str, re.Pattern[str], set[str]]] = [
    (
        "deprecated src.websocket_actions import",
        re.compile(r"^\s*(?:from|import)\s+src\.websocket_actions\b", re.MULTILINE),
        set(),
    ),
    (
        "deprecated src.manager import",
        re.compile(r"^\s*(?:from|import)\s+src\.manager\b", re.MULTILINE),
        set(),
    ),
    (
        "deprecated webui api client import",
        re.compile(
            r"""^\s*(?:import|export)\b[^\n]*['"][^'"]*api/client(?:\.[jt]sx?)?['"]""",
            re.MULTILINE,
        ),
        set(),
    ),
    (
        "archive import",
        re.compile(r"^\s*(?:from|import)\s+src\._archive\b", re.MULTILINE),
        set(),
    ),
    (
        "retired tui import",
        re.compile(r"^\s*(?:from|import)\s+tui\b", re.MULTILINE),
        set(),
    ),
]

FEATURE_THEME_IMPORT = re.compile(
    r"""^\s*(?:import|export)\b[^\n]*['"][^'"]*(?:\.\./)+(?:themes/|operations-console/)""",
    re.MULTILINE,
)
PAGE_CSS_IMPORT = re.compile(r"^\s*import\s+['\"].+\.css['\"]", re.MULTILINE)
THEME_CROSS_IMPORT = re.compile(
    r"""^\s*(?:import|export)\b[^\n]*['"][^'"]*themes/operations-console/""",
    re.MULTILINE,
)
ULTIMUR_LEGACY_CSS_IMPORT = re.compile(
    r"""^\s*@import\s+['"][^'"]*(?:pages/UserProfilePage\.css|styles/pages/)""",
    re.MULTILINE,
)
SOURCE_TREE_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+src(?:\.|\b)",
    re.MULTILINE,
)
DEVELOPMENT_LAYOUT_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:src\.)?"
    r"(?:UltimaScraperBackendMini|UltimaScraperCore|UltimaScraperDBArchive)(?:\.|\b)",
    re.MULTILINE,
)

PACKAGED_PYTHON_ROOTS: list[tuple[str, Path]] = [
    ("main.py", ROOT / "main.py"),
    (
        "../UltimaScraperCore/ultima_scraper_core",
        ROOT.parent / "UltimaScraperCore" / "ultima_scraper_core",
    ),
    (
        "../UltimaBackends/UltimaScraperBackend/ultima_scraper_backend",
        ROOT.parent
        / "UltimaBackends"
        / "UltimaScraperBackend"
        / "ultima_scraper_backend",
    ),
]

BANNED_FILE_PATTERNS = [
    "tests/test_tui_*.py",
    "tests/*.bak",
    "src/UltimaScraperWeb/webui/src/pages/*_old.*",
    "src/UltimaScraperWeb/webui/src/api/client.ts",
    "src/UltimaScraperWeb/webui/src/themes/ultimur*",
]


def iter_source_files() -> list[Path]:
    include_roots = ["src", "tests", "scripts", ".github"]
    files: list[Path] = []
    for root_name in include_roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}
            and "node_modules" not in path.parts
            and "dist" not in path.parts
        )
    return files


def main() -> int:
    violations: list[str] = []

    for path in iter_source_files():
        relative_path = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for label, pattern, allowlist in CHECKS:
            if relative_path in allowlist:
                continue
            if pattern.search(text):
                violations.append(f"{relative_path}: {label}")

        if relative_path.startswith("src/UltimaScraperWeb/webui/src/features/") and FEATURE_THEME_IMPORT.search(text):
            violations.append(f"{relative_path}: features must not import themes")

        if relative_path.startswith("src/UltimaScraperWeb/webui/src/pages/") and PAGE_CSS_IMPORT.search(text):
            violations.append(f"{relative_path}: pages must not import CSS directly")

        if (relative_path.startswith("src/UltimaScraperWeb/webui/src/themes/ultimur/") or relative_path.startswith("src/UltimaScraperWeb/webui/src/themes/ultimur-v2/")) and THEME_CROSS_IMPORT.search(text):
            violations.append(f"{relative_path}: ULTIMUR theme must not import operations-console internals")

        if (relative_path.startswith("src/UltimaScraperWeb/webui/src/themes/ultimur/") or relative_path.startswith("src/UltimaScraperWeb/webui/src/themes/ultimur-v2/")) and ULTIMUR_LEGACY_CSS_IMPORT.search(text):
            violations.append(f"{relative_path}: ULTIMUR theme must not import legacy page CSS directly")

    for pattern in BANNED_FILE_PATTERNS:
        for path in ROOT.glob(pattern):
            violations.append(f"{path.relative_to(ROOT).as_posix()}: banned retired artifact")

    for root_name, package_root in PACKAGED_PYTHON_ROOTS:
        paths = [package_root] if package_root.is_file() else package_root.rglob("*.py")
        for path in paths:
            source = path.read_text(encoding="utf-8")
            relative_path = root_name
            if not package_root.is_file():
                relative_path = (
                    f"{root_name}/{path.relative_to(package_root).as_posix()}"
                )
            if SOURCE_TREE_IMPORT.search(source):
                violations.append(
                    f"{relative_path}: installed runtime must not import the source tree"
                )
            if DEVELOPMENT_LAYOUT_IMPORT.search(source):
                violations.append(
                    f"{relative_path}: installed runtime must use distribution package names"
                )

    if violations:
        print("[boundaries] violations found:", file=sys.stderr)
        for violation in sorted(violations):
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print("[boundaries] import and artifact checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
