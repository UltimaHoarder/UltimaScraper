#!/bin/sh
set -eu

# The image runs one role per container. Each role's defaults are the ones its
# own image used to set; anything already in the environment wins.
container_role="${USR_CONTAINER_ROLE:-api}"
case "$container_role" in
    api)
        : "${USR_EXPECTED_DATABASE:=ultima_archive}" "${CONTROL_HOST:=0.0.0.0}" \
            "${CONTROL_PORT:=21121}" "${USR_ALLOW_REMOTE_BIND:=true}"
        export USR_EXPECTED_DATABASE CONTROL_HOST CONTROL_PORT USR_ALLOW_REMOTE_BIND
        ;;
    worker)
        : "${USR_WORKER_READINESS_FILE:=/dev/shm/usr-worker-readiness.json}"
        export USR_WORKER_READINESS_FILE
        ;;
    webui)
        : "${USR_WEBUI_HOST:=0.0.0.0}" "${USR_WEBUI_PORT:=21120}" "${USR_WEBUI_DATA_DIR:=/data}" \
            "${USR_WEBUI_STATIC_DIR:=/opt/webui/static}"
        export USR_WEBUI_HOST USR_WEBUI_PORT USR_WEBUI_DATA_DIR USR_WEBUI_STATIC_DIR
        # The WebUI server needs none of the backend's secrets or database settings.
        if [ "$*" = ultimascraper ]; then
            set -- ultimascraper-webui
        fi
        exec "$@"
        ;;
esac

load_secret_file() {
    variable_name="$1"
    allow_empty="${2:-false}"
    file_variable_name="${variable_name}_FILE"
    direct_value="$(printenv "$variable_name" 2>/dev/null || true)"
    secret_file="$(printenv "$file_variable_name" 2>/dev/null || true)"

    if [ -n "$direct_value" ] && [ -n "$secret_file" ]; then
        echo "Set only one of $variable_name or $file_variable_name." >&2
        exit 1
    fi
    if [ -n "$secret_file" ]; then
        if [ ! -r "$secret_file" ]; then
            echo "$file_variable_name does not reference a readable file." >&2
            exit 1
        fi
        secret_value="$(tr -d '\r\n' < "$secret_file")"
        if [ -z "$secret_value" ]; then
            if [ "$allow_empty" = "true" ]; then
                unset "$variable_name"
            else
                echo "$file_variable_name references an empty file." >&2
                exit 1
            fi
        else
            export "$variable_name=$secret_value"
        fi
    fi
}

for variable_name in \
    USR_ADMIN_TOKEN \
    USR_SECRET_KEY \
    USR_SECRET_KEY_PREVIOUS \
    ULTIMA_ARCHIVE_DATABASE_URL \
    DATABASE_URL
do
    load_secret_file "$variable_name"
done
load_secret_file REDIS_PASSWORD true

# .env.example ships replace-with-... values; running with one would publish a
# well-known credential.
for variable_name in \
    USR_ADMIN_TOKEN \
    USR_SECRET_KEY \
    USR_SECRET_KEY_PREVIOUS \
    ULTIMA_ARCHIVE_DATABASE_URL \
    DATABASE_URL \
    REDIS_PASSWORD \
    POSTGRES_PASSWORD
do
    case "$(printenv "$variable_name" 2>/dev/null || true)" in
        *replace-with-*)
            case "$variable_name" in
                USR_ADMIN_TOKEN|USR_SECRET_KEY)
                    hint="leave it empty to have one generated, or set your own"
                    ;;
                *)
                    hint="set a real value"
                    ;;
            esac
            echo "$variable_name still has the .env.example placeholder; $hint." >&2
            exit 1
            ;;
    esac
done

generated_secrets_dir="${USR_GENERATED_SECRETS_DIR:-$HOME/.config/ultima_scraper_verse/secrets}"

# An unset secret is generated once and kept in the config volume, so the
# backend and worker containers that share it read the same value.
use_generated_secret() {
    variable_name="$1"
    if [ -n "$(printenv "$variable_name" 2>/dev/null || true)" ]; then
        return
    fi
    secret_file="$generated_secrets_dir/$variable_name"
    if [ ! -s "$secret_file" ]; then
        mkdir -p -m 0700 "$generated_secrets_dir"
        candidate="$(mktemp "$generated_secrets_dir/.$variable_name.XXXXXX")"
        python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$candidate"
        # ln refuses an existing target, so concurrent first starts keep one value.
        if ln "$candidate" "$secret_file" 2>/dev/null; then
            echo "Generated $variable_name in $secret_file; keep a backup of it." >&2
        fi
        rm -f "$candidate"
    fi
    export "$variable_name=$(tr -d '\r\n' < "$secret_file")"
}

case "$container_role:${RUN_MODE:-$container_role}" in
    api:api)
        RUN_MODE=api
        ;;
    worker:worker)
        RUN_MODE=worker
        ;;
    *)
        echo "The USR $container_role container cannot start the requested RUN_MODE." >&2
        exit 1
        ;;
esac
export RUN_MODE

if [ "$container_role" = api ]; then
    use_generated_secret USR_ADMIN_TOKEN
fi

# DATABASE_URL is the deprecated alias of the canonical archive URL; only the
# canonical name reaches the application.
if [ -n "${DATABASE_URL:-}" ]; then
    if [ -n "${ULTIMA_ARCHIVE_DATABASE_URL:-}" ] && [ "$ULTIMA_ARCHIVE_DATABASE_URL" != "$DATABASE_URL" ]; then
        echo "ULTIMA_ARCHIVE_DATABASE_URL and the deprecated DATABASE_URL differ; set only ULTIMA_ARCHIVE_DATABASE_URL." >&2
        exit 1
    fi
    echo "DATABASE_URL is deprecated; set ULTIMA_ARCHIVE_DATABASE_URL instead." >&2
    ULTIMA_ARCHIVE_DATABASE_URL="$DATABASE_URL"
fi
unset DATABASE_URL

if [ -z "${ULTIMA_ARCHIVE_DATABASE_URL:-}" ]; then
    for variable_name in POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
        variable_value="$(printenv "$variable_name" 2>/dev/null || true)"
        if [ -z "$variable_value" ]; then
            echo "Set ULTIMA_ARCHIVE_DATABASE_URL or all POSTGRES_* connection variables for the USR backend container." >&2
            exit 1
        fi
    done
    ULTIMA_ARCHIVE_DATABASE_URL="$(
        python -c 'import os; from sqlalchemy.engine import URL; print(URL.create("postgresql+psycopg", username=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]), database=os.environ["POSTGRES_DB"]).render_as_string(hide_password=False))'
    )"
fi
export ULTIMA_ARCHIVE_DATABASE_URL

if [ -z "${REDIS_HOST:-}" ]; then
    echo "REDIS_HOST must be set for the USR backend container." >&2
    exit 1
fi

case "${USR_ENCRYPT_SECRETS:-true}" in
    0|false|FALSE|no|NO|off|OFF)
        ;;
    *)
        use_generated_secret USR_SECRET_KEY
        ;;
esac

exec "$@"
