#!/bin/sh
# The image's healthcheck: checks the role this container runs. It does not see
# what the entrypoint exported, so it picks the role by the entrypoint's rule.
if [ -n "${USR_CONTAINER_ROLE:-}" ]; then
    container_role="$USR_CONTAINER_ROLE"
elif [ -z "${ULTIMA_ARCHIVE_DATABASE_URL:-}${ULTIMA_ARCHIVE_DATABASE_URL_FILE:-}${DATABASE_URL:-}${DATABASE_URL_FILE:-}${POSTGRES_HOST:-}${REDIS_HOST:-}" ]; then
    container_role=webui
else
    container_role=api
fi
case "$container_role" in
    api)
        exec curl --fail --silent --show-error --output /dev/null \
            "http://127.0.0.1:${CONTROL_PORT:-21121}/api/v1/admin/health"
        ;;
    worker)
        # The healthcheck does not see what the entrypoint exported.
        RUN_MODE="${RUN_MODE:-worker}" exec python /usr/local/bin/usr-worker-healthcheck
        ;;
    webui)
        # HTTP or HTTPS, as USR_WEBUI_TLS* configure it.
        exec python -m ultima_webui_server.healthcheck
        ;;
esac
echo "Unknown USR_CONTAINER_ROLE: ${container_role}" >&2
exit 1
