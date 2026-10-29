# Native Development Guide

This guide walks through running, modifying, and testing UltimaScraper directly from source on Linux using Python 3.14 and `uv`.

---

## 1. Prerequisites

- **Python**: Strict Python 3.14 (`>=3.14,<3.15`)
- **uv**: Fast package manager (`>=0.13.0`)
- **Node.js & npm**: Node.js 20+ and npm 10+ (for WebUI development)
- **PostgreSQL 16+ with pgvector**: Authoritative storage (listening locally or reachable over network). pgvector is required, see [Installing pgvector](#installing-pgvector).
- **Redis 7+**: Queue and messaging broker (listening locally or reachable over network)

> [!TIP]
> If you have Docker installed, spin up local PostgreSQL and Redis instances in seconds:
> ```bash
> docker compose up -d postgres redis
> ```
> The bundled `postgres` service already includes pgvector.

### Installing pgvector

A PostgreSQL you installed yourself needs the pgvector package for its major version:

| Platform | Command |
|---|---|
| Debian / Ubuntu ([PGDG repository](https://wiki.postgresql.org/wiki/Apt)) | `sudo apt install postgresql-16-pgvector` |
| Fedora / RHEL ([PGDG repository](https://www.postgresql.org/download/linux/redhat/)) | `sudo dnf install pgvector_16` |
| Arch Linux | `sudo pacman -S pgvector` |
| macOS (Homebrew) | `brew install pgvector` |

Change `16` to your server's major version. If your platform has no package, build it from [source](https://github.com/pgvector/pgvector#installation).

The backend creates the extension when it connects. If its database user isn't allowed to, run this once as a superuser in the archive database:

```bash
sudo -u postgres psql -d ultima_archive -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;'
```

---

## 2. Environment Synchronization

Clone the repository and synchronize dependencies using `uv`:

```bash
git clone https://github.com/UltimaHoarder/UltimaScraper.git
cd UltimaScraper

# Synchronize all runtime, dev, and docs dependencies
uv sync --python 3.14 --group dev --group docs
```

The workspace utilizes editable sibling sources (`[tool.uv.sources]` in `pyproject.toml`) for active cross-module development across the USV framework.

---

## 3. Bootstrap Runtime Secrets

Generate the local `.env` file with generated encryption keys, admin bearer tokens, and connection strings:

```bash
cp .env.example .env
uv run python -m ultima_scraper_backend.bootstrap --compose --env-file .env
```

Verify that the database is reachable and all schema migrations are up to date:

```bash
uv run python -m ultima_scraper_backend.bootstrap --check
```

---

## 4. WebUI Frontend Setup

The WebUI frontend resides in `src/UltimaScraperWeb/webui`.

### Production Build
Build the optimized static assets that the launcher serves:

```bash
npm --prefix src/UltimaScraperWeb/webui ci
npm --prefix src/UltimaScraperWeb/webui run build:production
```

### Vite Dev Server (Hot Module Replacement)
For UI feature development with instant hot reloading:

```bash
npm --prefix src/UltimaScraperWeb/webui run dev
```

---

## 5. Launching the Application

Start the unified development runtime using `main.py`:

```bash
uv run python main.py
```

`main.py` coordinates:
- The FastAPI control plane and WebSocket hub (`:8000`).
- Background worker pools and database writer leases.
- The `ultima_webui_server` gateway (`:21120` in development, `:21120` in production).

Open **`http://localhost:21120`** in your browser. If this is a fresh setup with no configured connections, you will be automatically redirected to `/setup` to complete backend storage, Widevine DRM device registration, and platform authentications.

---

## 6. Testing & Quality Gates

Run the test suite across components:

```bash
# Run backend pytest suite
uv run pytest

# Run WebUI lint and test suite
npm --prefix src/UltimaScraperWeb/webui run lint
npm --prefix src/UltimaScraperWeb/webui run test:unit

# Test documentation build in strict mode
uv run --group docs zensical build --strict

# Run the complete release verification pipeline
./scripts/release/check.sh
```
