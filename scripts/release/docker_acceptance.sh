#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_NAME="${USR_ACCEPTANCE_PROJECT:-usr-release-acceptance-$$}"
KEEP_RESOURCES="${USR_ACCEPTANCE_KEEP:-0}"

cd "$ROOT_DIR"

# Empty: the containers generate both on first start, as for a new user.
export USR_ADMIN_TOKEN=""
export USR_ENCRYPT_SECRETS="true"
export USR_SECRET_KEY=""
export ULTIMA_ARCHIVE_DATABASE_URL=""
export DATABASE_URL=""
export POSTGRES_USER="ultimascraper"
export POSTGRES_PASSWORD="pg@pass:with/slash"
export POSTGRES_DB="ultima_archive"
export REDIS_HOST="redis"
export REDIS_PASSWORD="redis@pass:with/slash"
export USR_WEB_PORT="0"
export USR_REQUIRE_WHEELHOUSE="1"
export USR_VERSION="acceptance"

compose=(
    docker compose
    -p "$PROJECT_NAME"
    -f "$ROOT_DIR/docker-compose.yml"
    -f "$ROOT_DIR/docker-compose.build.yml"
)

cleanup() {
    exit_code=$?
    trap - EXIT INT TERM
    if [[ $exit_code -ne 0 ]]; then
        "${compose[@]}" logs --no-color || true
    fi
    if [[ "$KEEP_RESOURCES" != "1" ]]; then
        "${compose[@]}" down --volumes --remove-orphans || true
    else
        echo "Acceptance resources retained: $PROJECT_NAME"
    fi
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

assert_success() {
    RESPONSE_JSON="$1" python3.14 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE_JSON"])
if payload.get("success") is not True:
    raise SystemExit(f"Expected success response, received: {payload}")
PY
}

assert_setup_complete() {
    RESPONSE_JSON="$1" python3.14 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE_JSON"])
expected = {"is_configured": True, "has_config": True, "has_database": True}
actual = {key: payload.get(key) for key in expected}
if actual != expected:
    raise SystemExit(f"Setup state mismatch: {actual}")
PY
}

assert_plugin_metadata() {
    RESPONSE_JSON="$1" python3.14 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE_JSON"])
if payload.get("manifest_schema_version") not in payload.get("supported_manifest_schema_versions", []):
    raise SystemExit(f"Unexpected plugin metadata: {payload}")
if not isinstance(payload.get("capabilities"), list):
    raise SystemExit(f"Plugin capabilities are missing: {payload}")
if not isinstance(payload.get("event_families"), list):
    raise SystemExit(f"Plugin event families are missing: {payload}")
PY
}

assert_plugin_record() {
    RESPONSE_JSON="$1" EXPECTED_PLUGIN_ID="$2" python3.14 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE_JSON"])
expected_plugin_id = os.environ["EXPECTED_PLUGIN_ID"]
if payload.get("plugin_id") != expected_plugin_id:
    raise SystemExit(f"Plugin ID mismatch: {payload}")
if payload.get("status") != "disabled":
    raise SystemExit(f"Plugin status mismatch: {payload}")
PY
}

"$ROOT_DIR/scripts/release/build_docker_wheelhouse.sh"
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d --no-build --wait --wait-timeout 180

[[ "$("${compose[@]}" exec -T backend id -u)" == "1000" ]]
[[ "$("${compose[@]}" exec -T worker id -u)" == "1000" ]]
[[ "$("${compose[@]}" exec -T webui id -u)" != "0" ]]
[[ "$(docker inspect -f '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$("${compose[@]}" ps -q backend)")" == "$USR_VERSION" ]]
[[ "$(docker inspect -f '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$("${compose[@]}" ps -q worker)")" == "$USR_VERSION" ]]
[[ "$(docker inspect -f '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$("${compose[@]}" ps -q webui)")" == "$USR_VERSION" ]]
"${compose[@]}" exec -T backend python -c 'import sys; assert sys.version_info[:2] == (3, 14)'
"${compose[@]}" exec -T worker python -c 'import sys; assert sys.version_info[:2] == (3, 14)'
"${compose[@]}" exec -T backend python -c 'import main, ultima_scraper_backend, ultima_scraper_db_archive; modules = (main, ultima_scraper_backend, ultima_scraper_db_archive); assert all(str(module.__file__).startswith("/opt/venv/") for module in modules)'
"${compose[@]}" exec -T worker python -c 'import main, ultima_scraper_backend, ultima_scraper_db_archive; modules = (main, ultima_scraper_backend, ultima_scraper_db_archive); assert all(str(module.__file__).startswith("/opt/venv/") for module in modules)'
"${compose[@]}" exec -T backend python -c 'import packaging; from ultima_scraper_backend.plugin_system.platform import PluginPlatform; assert PluginPlatform.__module__ == "ultima_scraper_backend.plugin_system.platform"'
"${compose[@]}" exec -T backend test ! -e /app/src
"${compose[@]}" exec -T worker test ! -e /app/src
# DRM downloads need Bento4's tools first on the path (pymp4 ships its own mp4dump).
[[ "$("${compose[@]}" exec -T worker sh -c 'command -v mp4decrypt; command -v mp4dump' | tr -d '\r')" == $'/opt/bento4/bin/mp4decrypt\n/opt/bento4/bin/mp4dump' ]]
[[ "$("${compose[@]}" exec -T backend printenv USR_PLUGINS_DIR)" == "/app/__user_data__/plugins" ]]
"${compose[@]}" exec -T backend test -w /app/__user_data__/plugins
[[ "$("${compose[@]}" exec -T webui python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:21120/health").read().decode().strip())')" == "healthy" ]]
[[ "$("${compose[@]}" exec -T backend curl -sS -o /dev/null -w '%{http_code}' http://webui:21120/api/v1/system/bootstrap)" == "401" ]]

# The backend generates its secrets on first start and keeps them in the config
# volume, where the WebUI reads the admin token. No browser is ever handed it:
# there is no setup link in the log and no public claim route.
generated_secrets_dir=/home/ultimascraper/.config/ultima_scraper_verse/secrets
"${compose[@]}" exec -T backend test -s "$generated_secrets_dir/USR_ADMIN_TOKEN"
"${compose[@]}" exec -T worker test -s "$generated_secrets_dir/USR_SECRET_KEY"
ADMIN_TOKEN="$("${compose[@]}" exec -T backend cat "$generated_secrets_dir/USR_ADMIN_TOKEN")"
if "${compose[@]}" logs --no-color backend | grep -q '#claim='; then
    echo "The backend logged a setup link" >&2
    exit 1
fi
[[ "$("${compose[@]}" exec -T backend curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data '{}' http://webui:21120/api/v1/setup/claim)" == "401" ]]

# The WebUI server: the first visitor on its network sets its password, then
# reaches the backend through /b/default with only the session cookie. The
# backend's token is added by the WebUI server and never sent to the browser.
webui_session="$("${compose[@]}" exec -T backend curl -fsS http://webui:21120/webui/api/v1/session)"
RESPONSE_JSON="$webui_session" python3.14 - <<'PY'
import json
import os

session = json.loads(os.environ["RESPONSE_JSON"])
expected = {"authenticated": False, "password_set": False, "can_claim": True, "default_connection": "default"}
if session != expected:
    raise SystemExit(f"Unexpected WebUI session state: {session}")
PY
"${compose[@]}" exec -T backend curl -fsS -c /tmp/webui-cookies -X POST \
    -H 'Content-Type: application/json' --data '{"password":"acceptance-webui-password"}' \
    http://webui:21120/webui/api/v1/session/claim
proxied_backend="$("${compose[@]}" exec -T backend curl -fsS -b /tmp/webui-cookies http://webui:21120/b/default/api/v1/system/backend)"
[[ "$proxied_backend" != *"$ADMIN_TOKEN"* ]]
[[ "$("${compose[@]}" exec -T backend curl -fsS -b /tmp/webui-cookies http://webui:21120/webui/api/v1/connections)" != *"$ADMIN_TOKEN"* ]]
[[ "$("${compose[@]}" exec -T backend curl -sS -o /dev/null -w '%{http_code}' http://webui:21120/b/default/api/v1/system/backend)" == "401" ]]

plugin_metadata_response="$(
    "${compose[@]}" exec -T backend curl -fsS \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        http://127.0.0.1:21121/api/v1/plugins/metadata
)"
assert_plugin_metadata "$plugin_metadata_response"

database_response="$(
    "${compose[@]}" exec -T backend curl -fsS --max-time 330 \
        -X POST \
        -H 'Content-Type: application/json' \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        --data '{"host":"postgres","port":5432,"name":"ultima_archive","username":"ultimascraper","password":"pg@pass:with/slash"}' \
        http://127.0.0.1:21121/api/v1/setup/test-database
)"
assert_success "$database_response"

redis_response="$(
    "${compose[@]}" exec -T backend curl -fsS --max-time 30 \
        -X POST \
        -H 'Content-Type: application/json' \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        --data '{"host":"redis","port":6379,"db":0,"password":"redis@pass:with/slash","enabled":true}' \
        http://127.0.0.1:21121/api/v1/setup/test-redis
)"
assert_success "$redis_response"

complete_response="$(
    "${compose[@]}" exec -T backend curl -fsS --max-time 120 \
        -X POST \
        -H 'Content-Type: application/json' \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        --data '{"database":{"host":"postgres","port":5432,"name":"ultima_archive","username":"ultimascraper","password":"pg@pass:with/slash"},"redis":{"host":"redis","port":6379,"db":0,"password":"redis@pass:with/slash","enabled":true}}' \
        http://127.0.0.1:21121/api/v1/setup/complete
)"
assert_success "$complete_response"

plugin_create_response="$(
    "${compose[@]}" exec -T backend curl -fsS --max-time 30 \
        -X POST \
        -H 'Content-Type: application/json' \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        --data '{"plugin_id":"acceptance-plugin","plugin_version":"1.0.0","display_name":"Acceptance Plugin","description":"Docker persistence check","usr_compatibility":">=0.1.0","capabilities":[]}' \
        http://127.0.0.1:21121/api/v1/plugins
)"
assert_plugin_record "$plugin_create_response" "acceptance-plugin"
"${compose[@]}" exec -T backend test -f /app/__user_data__/plugins/acceptance-plugin/manifest.yaml

extension_rows="$(
    "${compose[@]}" exec -T postgres psql \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -Atc "SELECT e.extname || '|' || n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname IN ('pg_trgm','uuid-ossp') ORDER BY e.extname"
)"
[[ "$extension_rows" == $'pg_trgm|public\nuuid-ossp|public' ]]

migration_head="$(
    "${compose[@]}" exec -T postgres psql \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -Atc 'SELECT version_num FROM public.alembic_version'
)"
# The database must be at the head of the migrations shipped in the image.
expected_migration_head="$(
    "${compose[@]}" exec -T backend python -c '
from alembic.config import Config
from alembic.script import ScriptDirectory
from ultima_scraper_db_archive import MIGRATION_BUNDLE
config = Config()
config.set_main_option("script_location", str(MIGRATION_BUNDLE.script_path))
print(" ".join(ScriptDirectory.from_config(config).get_heads()))'
)"
[[ -n "$migration_head" && "$migration_head" == "$expected_migration_head" ]]

"${compose[@]}" up -d --no-build --no-deps --force-recreate backend
"${compose[@]}" up -d --no-build --wait --wait-timeout 180

setup_status="$(
    "${compose[@]}" exec -T backend curl -fsS \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        http://127.0.0.1:21121/api/v1/setup/status
)"
assert_setup_complete "$setup_status"

plugin_status="$(
    "${compose[@]}" exec -T backend curl -fsS \
        -H "x-usr-admin-token: $ADMIN_TOKEN" \
        http://127.0.0.1:21121/api/v1/plugins/acceptance-plugin
)"
assert_plugin_record "$plugin_status" "acceptance-plugin"
# Plugin records live in PostgreSQL; the SQLite runtime file is only a legacy import source.
[[ "$(
    "${compose[@]}" exec -T postgres psql \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -Atc "SELECT to_regclass('management.plugin_repository_meta') IS NOT NULL"
)" == "t" ]]
"${compose[@]}" exec -T backend test -f /app/__user_data__/plugins/acceptance-plugin/manifest.yaml

"${compose[@]}" exec -T backend curl -fsS \
    -H "x-usr-admin-token: $ADMIN_TOKEN" \
        http://webui:21120/api/v1/system/bootstrap >/dev/null

# HTTPS: the WebUI recreated with a self-signed certificate stays healthy (its
# healthcheck follows the scheme), answers only HTTPS, and sets a Secure cookie.
USR_WEBUI_TLS=self-signed USR_WEBUI_TLS_HOSTNAMES=webui \
    "${compose[@]}" up -d --no-build --no-deps --force-recreate --wait --wait-timeout 120 webui
[[ "$("${compose[@]}" exec -T backend curl -fsSk https://webui:21120/health)" == "healthy" ]]
[[ "$("${compose[@]}" exec -T backend curl -sS -o /dev/null -w '%{http_code}' http://webui:21120/health 2>/dev/null || true)" != "200" ]]
tls_cookie="$("${compose[@]}" exec -T backend curl -sSk -D - -o /dev/null -b /tmp/webui-cookies \
    -X POST -H 'Content-Type: application/json' -H 'Origin: https://webui:21120' \
    --data '{"password":"acceptance-webui-password"}' https://webui:21120/webui/api/v1/session/login)"
[[ "$tls_cookie" == *"usr_webui_session="*"Secure"* ]]

echo "Docker release acceptance passed: $PROJECT_NAME"
