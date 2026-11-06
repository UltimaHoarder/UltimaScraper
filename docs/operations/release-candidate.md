# Release Candidate Verification & Quality Gates

Every release of UltimaScraper passes through strict automated gates before publishing container images or distribution wheels.

---

## Release Check Pipeline

The primary release validation script is located at `scripts/release/check.sh`.

```bash
# Run local release verification suite
./scripts/release/check.sh

# Include isolated Docker acceptance test
./scripts/release/check.sh --docker
```

### Automated Stages

1. **Backend Test Suite**:
   - Executes `pytest` with coverage thresholds across all core modules, write queue handlers, and job execution engines.
2. **WebUI Build & Test**:
   - `npm ci` clean package installation.
   - `npm audit --omit=dev --audit-level=high` security vulnerability scanning.
   - `npm run lint` ESLint code style and hygiene validation.
   - `npm run typecheck:tests` TypeScript strict type checking.
   - `npm run test:unit` Vitest component and logic tests.
   - `npm run build:production` Vite static production asset bundle generation.
   - `npm run test:smoke` Browser smoke verification.
3. **Documentation Strictness Gate**:
   - `zensical build --strict`: Builds the entire documentation site with strict error enforcement. The build fails if any dead links, syntax anomalies, or missing pages are detected.
4. **Distribution Artifacts**:
   - Builds distribution wheels and packages for release staging.
5. **Isolated Docker Acceptance (Optional `--docker`)**:
   - Spins up ephemeral test containers, initializes a temporary PostgreSQL and Redis instance, exercises the setup wizard, verifies API health, and tears down cleanly.

---

## Tagging & Image Publishing

1. **Version Alignment**: Ensure `pyproject.toml` and `package.json` reflect the target version (e.g. `0.1.0`).
2. **Git Tagging**: Create and push an annotated git tag matching the version:
   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push https://github.com/UltimaHoarder/UltimaScraper.git v0.1.0
   git push origin v0.1.0
   ```
3. **Automated CI Build**: The GitHub Actions release workflow (`.github/workflows/release.yml`) builds multi-architecture images for both `linux/amd64` and `linux/arm64` and publishes them to `ghcr.io/ultimahoarder/ultimascraper/{ultimascraper,backend,worker,webui}`, the images Docker Compose and the setup wizard use.
4. **WebUI package**: The Forgejo workflow (`.forgejo/workflows/webui-package.yml`) publishes `ultima-scraper-webui-server` to the Forgejo PyPI registry, which WebUIs installed with `uv tool install` update from. See [Updating the WebUI](webui-server.md#updating-the-webui).

### Image tags

| Trigger | Tags pushed | Notes |
|---|---|---|
| Tag `vX.Y.Z` (must match `pyproject.toml`) | `X.Y.Z`, `X.Y`, `latest`, `sha-<commit>` | A release version is never overwritten; the run fails if `X.Y.Z` already exists. |
| Push to `main` (or a manual run) | `X.Y.Z-edge.<commit>`, `edge`, `sha-<commit>` | A prerelease of the coming version. It never writes `X.Y.Z` or `latest`. |

Pin a release (`0.1.0`) for real deployments. Use `edge` to try `main` on a test host, for example with **Upgrade** under Backends → Deployments.

The workflow runs on GitHub's own runners and pushes with the run's own token, so each ghcr package must give the UltimaScraper repository write access (package settings → **Manage Actions access**). It needs no secrets.

The WebUI package workflow needs a Forgejo runner labelled `self-hosted`, `linux`, `amd64` with Node.js, `uv` and Python 3.14, and the `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` Actions secrets: a Forgejo user and an access token that can write packages.

### Build cache

The workflow keeps BuildKit's cache in `ghcr.io/ultimahoarder/ultimascraper/buildcache`, one tag per image. Every build reads it and every push writes it back, so the next run reuses each unchanged layer.

The Dockerfiles are ordered for it:

- the system packages and the third-party dependencies are rebuilt only when the base image, `docker/requirements.lock` or `docker/webui-requirements.lock` change;
- a build's own code (the first-party wheels, `main.py`, the WebUI server) is pure Python, installed once on the build host's own platform and copied into every image as a small layer, so arm64 does not build it under QEMU;
- version and revision build arguments are declared after the heavy steps, because a build argument used by a `RUN` step makes that step miss the cache whenever its value changes.

So a typical `main` build redoes only the first-party layers. The first run, or a run after a lock file changes, builds everything.

Images are pushed one at a time: the full, backend and worker images share most layers, so each later image reuses what the first one uploaded.
