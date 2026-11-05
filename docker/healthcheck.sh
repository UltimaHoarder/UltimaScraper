#!/bin/sh
# The image's healthcheck: checks the role this container runs.
case "${USR_CONTAINER_ROLE:-api}" in
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
echo "Unknown USR_CONTAINER_ROLE: ${USR_CONTAINER_ROLE}" >&2
exit 1
