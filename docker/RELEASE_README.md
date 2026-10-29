# UltimaScraper Docker release

This bundle deploys version-matched API-only backend, worker, and WebUI images.
It does not need the source repository or sibling repositories.

1. Copy `.env.example` to `.env` and replace every `replace-with-...` value.
   Leave `USR_ADMIN_TOKEN` and `USR_SECRET_KEY` empty to have them generated on
   first start.
2. Set `USR_BACKEND_IMAGE`, `USR_WORKER_IMAGE`, `USR_WEBUI_IMAGE`, and
   `USR_VERSION` to the
   immutable image references supplied by your release channel. If you loaded
   the matching image archive, the default image names can be used.
3. Choose the components in `COMPOSE_PROFILES`. The default runs the WebUI,
   backend, worker, PostgreSQL and Redis together:

   ```bash
   docker compose up -d
   ```

   Leave `postgres` or `redis` out and set `ULTIMA_ARCHIVE_DATABASE_URL` or
   `REDIS_HOST` to use existing servers. An existing PostgreSQL must be
   version 16 or newer with the pgvector extension installed; the bundled
   `postgres` service (`pgvector/pgvector:pg16`) already has it.

The WebUI is available on port `8080` by default. On first start, opening it
from the server's network goes straight to the setup wizard; from elsewhere,
use the single-use link printed by `docker compose logs backend`. PostgreSQL and Redis in the
bundled topology are isolated inside the Compose network and use persistent
named volumes. Plugin manifests and runtime state are persisted in the
`user_data` volume at `/app/__user_data__/plugins`.

The backend image cannot launch scrape workers even if its persisted config says
they are enabled. Only the explicit worker image consumes queued jobs.
