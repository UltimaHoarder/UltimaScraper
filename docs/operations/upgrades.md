# Upgrades & Database Migrations

This guide describes how to upgrade UltimaScraper installations safely, run database schema migrations, and perform backups and rollbacks.

---

## Upgrade Workflow (Docker Compose)

### 1. Create Pre-Upgrade Backup
Always back up both the PostgreSQL database and the configuration volume before applying an upgrade:

```bash
# 1. Export database dump
docker compose exec postgres pg_dump -U postgres ultima_archive > pre_upgrade_$(date +%Y%m%d_%H%M%S).sql

# 2. Archive config volume
docker run --rm -v ultimascraper_usr_config:/config -v $(pwd):/backup alpine \
    tar -czf /backup/pre_upgrade_config_$(date +%Y%m%d_%H%M%S).tar.gz -C /config .
```

### 2. Update Image Tag or Version
Edit `.env` to specify the new release tag:

```env
USR_VERSION=0.2.0
```

### 3. Pull and Apply
Coming from a version with separate backend, worker and WebUI images? Take `docker-compose.yml` from the new release too, and if your `.env` sets `USR_BACKEND_IMAGE`, `USR_WORKER_IMAGE` or `USR_WEBUI_IMAGE`, replace them with one `USR_IMAGE`. Installs made by the setup wizard get both from **Upgrade**.

Pull the new release image and recreate containers:

```bash
docker compose pull
docker compose up -d
```

### Bundled PostgreSQL image change (pgvector)

The bundled `postgres` service changed from `postgres:16-alpine` to `pgvector/pgvector:pg16`. Both are PostgreSQL 16 and the new image reuses the existing `postgres_data` volume. On the first `docker compose up -d` after upgrading, the container is recreated on the new image.

The old image was built on Alpine and the new one on Debian, and the two sort text differently. Rebuild the indexes once after the switch, or text lookups and unique checks can miss rows:

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "REINDEX DATABASE"'
```

On a large archive this takes a while and locks each table while its indexes rebuild, so stop the backend and workers first. Restoring a `pg_dump` into a fresh volume works too, and rebuilds every index.

If you don't use the bundled PostgreSQL, install pgvector on your server before upgrading (see [PostgreSQL Requirements](docker.md#postgresql-requirements-pgvector)).

---

## Database Migrations

UltimaScraper manages its database schema declaratively using asynchronous migration scripts:

- **Automatic Startup Application**: When the `backend` container starts, it inspects current schema revision markers in PostgreSQL. Any pending migrations are applied transactionally before incoming API traffic is accepted.
- **Fail-Safe Startup**: If a migration fails or the database schema is incompatible, the backend halts and emits diagnostic logs rather than serving requests with partial schemas.

### Verifying Schema Status Manually

To verify that the current database schema matches backend expectations:

```bash
# In Docker:
docker compose exec backend python -m ultima_scraper_backend.bootstrap --check

# In native development:
uv run python -m ultima_scraper_backend.bootstrap --check
```

---

## Rollback Procedure

If an upgrade encounters unexpected behavior or breaking hardware constraints:

1. Stop running containers:
   ```bash
   docker compose down
   ```
2. Revert the version tag in `.env` to the previous version:
   ```env
   USR_VERSION=0.1.0
   ```
3. If database migrations made schema modifications that are incompatible with the previous version, restore the database dump:
   ```bash
   docker compose up -d postgres
   docker compose exec -T postgres dropdb -U postgres ultima_archive
   docker compose exec -T postgres createdb -U postgres ultima_archive
   cat pre_upgrade_YYYYMMDD_HHMMSS.sql | docker compose exec -T postgres psql -U postgres ultima_archive
   ```
4. Restore previous config if necessary, then restart the stack:
   ```bash
   docker compose up -d
   ```
