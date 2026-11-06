# Environment Variables & Configuration Reference

This reference lists all configuration and resource tuning environment variables for UltimaScraper.

Every variable listed here is optional; when unset, sensible production defaults are automatically used.

---

## 1. Core Deployment & Container Variables

These variables configure service hostnames, ports, and release image specifications.

| Variable | Default | Description |
|---|---|---|
| `COMPOSE_PROFILES` | `webui,backend,worker,postgres,redis` | Comma-separated list of services enabled on this host. |
| `USR_VERSION` | `latest` | Release image tag to pull. Pin a version such as `0.1.0` to upgrade only when you choose. |
| `USR_WEB_PORT` | `21120` | External host port mapped to the WebUI server gateway. |
| `USR_ADMIN_TOKEN` | *Auto-generated* | Administrative bearer token securing the FastAPI backend. |
| `USR_SECRET_KEY` | *Auto-generated* | Encrypts secrets stored in PostgreSQL, such as auth cookies. Every backend and worker sharing a database must use the same value; one with a different key refuses to start. Rotate with `USR_SECRET_KEY_PREVIOUS`. |
| `USR_SECRET_KEY_PREVIOUS` | *Empty* | The old key while rotating `USR_SECRET_KEY`. Secrets encrypted with it can still be read. |
| `BACKEND_ID` | `usr-docker` | This backend's id in the cluster. Give each backend sharing a database its own. |
| `USR_WEBUI_SECRET_KEY` | *Auto-generated* | 32-byte secret key used for AES-GCM encryption of the WebUI's own stored credentials. |
| `USR_STORAGE_PATH` | `./data` | Local filesystem path mounted for media files and downloads. |
| `USR_IMAGE` | `ghcr.io/ultimahoarder/ultimascraper/ultimascraper` | The full image, which the backend, worker and WebUI containers run by default. |
| `USR_BACKEND_IMAGE` | *Empty* | Runs the backend from its own image instead, e.g. `ghcr.io/ultimahoarder/ultimascraper/backend`. |
| `USR_WORKER_IMAGE` | *Empty* | Runs the workers from their own image instead, e.g. `ghcr.io/ultimahoarder/ultimascraper/worker`. |
| `USR_WEBUI_IMAGE` | *Empty* | Runs the WebUI from its own, much smaller image instead, e.g. `ghcr.io/ultimahoarder/ultimascraper/webui`. |
| `USR_CONTAINER_ROLE` | *Picked from the settings* | What a container of the full image runs: `api` (the backend), `worker` or `webui`. `docker-compose.yml` sets it for each service. Unset, a container with no database or Redis settings runs the WebUI, and any other the backend. |

---

## 2. PostgreSQL Connection Settings

The server must be PostgreSQL 16 or newer with pgvector installed (see [PostgreSQL Requirements](../operations/docker.md#postgresql-requirements-pgvector)).

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_HOST` | `postgres` (or `127.0.0.1`) | Hostname or IP of the authoritative PostgreSQL server. |
| `POSTGRES_PORT` | `5432` | TCP port of the PostgreSQL service. |
| `POSTGRES_DB` | `ultima_archive` | Database name. |
| `POSTGRES_USER` | `postgres` | Database user account. |
| `POSTGRES_PASSWORD` | *Required* | Database user password. |

---

## 3. Redis Connection Settings

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `redis` (or `127.0.0.1`) | Hostname or IP of the Redis message broker. |
| `REDIS_PORT` | `6379` | TCP port of the Redis service. |
| `REDIS_PASSWORD` | *Required* | Authentication password for Redis. |

---

## 4. Database Writer Resource Controls

These variables control the throughput and concurrency of the globally leased database write aggregator:

| Variable | Default | Description |
|---|---|---|
| `ULTIMA_DATABASE_WRITER_CONCURRENCY` | `4` | Number of concurrent database connections allocated for write transactions. |
| `ULTIMA_DATABASE_WRITER_BATCH_SIZE` | `100` | Maximum number of write commands drained per database transaction. |
| `ULTIMA_DATABASE_WRITER_MAX_ATTEMPTS` | `8` | Maximum retry attempts for a failing batch before routing to dead-letter storage. |
| `ULTIMA_DATABASE_WRITER_RECLAIM_IDLE_MS` | `30000` | Milliseconds before an abandoned write batch is reclaimed by another writer. |
| `ULTIMA_DATABASE_WRITER_RETRY_DELAY_SECONDS` | `5` | Exponential backoff delay base between retry attempts. |
| `ULTIMA_DATABASE_WRITER_DEAD_LETTER_MAXLEN` | `10000` | Maximum number of dead-letter records retained in Redis for inspection. |
| `ULTIMA_DATABASE_WRITE_TIMEOUT_SECONDS` | `900` | Database write statement execution timeout in seconds. |

---

## 5. Deprecated & Relocated Settings

The following policy controls have moved from environment variables to database-backed application settings (`management.settings`):

| Deprecated Environment Variable | Replaced by Setting Key |
|---|---|
| `ULTIMA_WORKER_CONCURRENCY` | `worker_pool.task_concurrency` |
| `ULTIMA_CLAIM_BATCH_SIZE` | `worker_pool.claim_batch_size` |
| `USR_TERMINAL_JOB_RECONCILE_INTERVAL_SECONDS` | `job_execution.terminal_reconcile_interval_seconds` |
| `USR_TERMINAL_JOB_RECONCILE_MIN_AGE_SECONDS` | `job_execution.terminal_reconcile_min_age_seconds` |
| `USR_TERMINAL_JOB_RECONCILE_BATCH_SIZE` | `job_execution.terminal_reconcile_batch_size` |
| `USR_COMPLETED_JOB_RETENTION_SECONDS` | `job_execution.completed_job_retention_seconds` |
| `USR_COMPLETED_JOB_RETENTION_BATCH_SIZE` | `job_execution.completed_job_retention_batch_size` |
| `ULTIMA_JOB_TASK_ARCHIVE_BATCH_SIZE` | `job_execution.task_archive_batch_size` |
| `ULTIMA_MPS_REPLACEMENT_BATCH_SIZE` | `job_execution.mps_replacement_batch_size` |
| `ULTIMA_LEDGER_PLANNER_BATCH` | `job_execution.ledger_planner_batch` |
| `ULTIMA_MPS_GUEST_ROUTE_TIMEOUT` | `network.guest_route_timeout` |
| `ULTIMA_MPS_GUEST_LOOKUP_TIMEOUT` | `network.guest_lookup_timeout` |
