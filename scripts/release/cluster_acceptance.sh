#!/usr/bin/env bash
# End-to-end cluster check with the release images:
#
#   node-a, node-b  share one PostgreSQL database and Redis: one cluster.
#   node-c          has its own database on the same server: independent.
#
# A WebUI server whose default connection is node-a must report node-b as a
# member it has not added yet (at node-b's advertised address), keep node-c
# apart, and keep node-b in the cluster while it is down.
#
# Usage: cluster_acceptance.sh [VERSION]   (local images; default "acceptance")

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
work="$(mktemp -d)"
project="usr-cluster-acceptance-$$"

secret() { openssl rand -hex 24; }
web_port="$("$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
token_a="$(secret)"
token_b="$(secret)"
token_c="$(secret)"
postgres_password="$(secret)"
redis_password="$(secret)"

cat >"$work/.env" <<EOF
COMPOSE_PROFILES=webui,backend,worker,postgres,redis
USR_VERSION=${1:-acceptance}
USR_WEB_PORT=$web_port
BACKEND_ID=node-a
USR_PUBLIC_API_URL=http://backend:21121
USR_ADMIN_TOKEN=$token_a
# Members of one cluster decrypt each other's stored secrets.
USR_SECRET_KEY=$(secret)
POSTGRES_PASSWORD=$postgres_password
REDIS_PASSWORD=$redis_password
TOKEN_B=$token_b
TOKEN_C=$token_c
EOF

cat >"$work/cluster.yml" <<EOF
services:
  backend-b:
    extends: {file: $ROOT_DIR/docker-compose.yml, service: backend}
    environment:
      BACKEND_ID: node-b
      USR_PUBLIC_API_URL: http://backend-b:21121
      USR_ADMIN_TOKEN: \${TOKEN_B}
    volumes: !override
      - config_b:/home/ultimascraper/.config/ultima_scraper_verse
      - user_b:/app/__user_data__
  worker-b:
    extends: {file: $ROOT_DIR/docker-compose.yml, service: worker}
    depends_on: !reset []
    environment:
      BACKEND_ID: node-b
      USR_PUBLIC_API_URL: http://backend-b:21121
      USR_ADMIN_TOKEN: \${TOKEN_B}
    volumes: !override
      - config_b:/home/ultimascraper/.config/ultima_scraper_verse
      - user_b:/app/__user_data__
  backend-c:
    extends: {file: $ROOT_DIR/docker-compose.yml, service: backend}
    environment:
      BACKEND_ID: node-c
      USR_PUBLIC_API_URL: http://backend-c:21121
      USR_ADMIN_TOKEN: \${TOKEN_C}
      POSTGRES_DB: ultima_c
      USR_EXPECTED_DATABASE: ultima_c
    volumes: !override
      - config_c:/home/ultimascraper/.config/ultima_scraper_verse
      - user_c:/app/__user_data__
volumes:
  config_b:
  user_b:
  config_c:
  user_c:
EOF

compose=(docker compose --project-name "$project" --env-file "$work/.env"
    -f "$ROOT_DIR/docker-compose.yml" -f "$work/cluster.yml")
cleanup() {
    exit_code=$?
    if [[ $exit_code -ne 0 ]]; then "${compose[@]}" logs --tail 40 >&2 || true; fi
    if [[ -n "${USR_KEEP_STACK:-}" ]]; then
        echo "Kept: ${compose[*]}" >&2
        return
    fi
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf -- "$work"
    exit "$exit_code"
}
trap cleanup EXIT

"${compose[@]}" up -d --no-build --wait --wait-timeout 240 postgres redis
"${compose[@]}" exec -T postgres psql -U ultimascraper -d ultima_archive -qc 'CREATE DATABASE ultima_c'
"${compose[@]}" up -d --no-build --wait --wait-timeout 240

WEBUI="http://127.0.0.1:$web_port" PROJECT="$project" ENV_FILE="$work/.env" CLUSTER_FILE="$work/cluster.yml" \
ROOT_DIR="$ROOT_DIR" TOKEN_A="$token_a" TOKEN_B="$token_b" TOKEN_C="$token_c" \
POSTGRES_PASSWORD="$postgres_password" REDIS_PASSWORD="$redis_password" \
    "$PYTHON" - <<'PY'
import json
import os
import subprocess
import time

import httpx

env = os.environ
compose = [
    "docker", "compose", "--project-name", env["PROJECT"], "--env-file", env["ENV_FILE"],
    "-f", f"{env['ROOT_DIR']}/docker-compose.yml", "-f", env["CLUSTER_FILE"],
]
nodes = {
    "a": ("http://backend:21121", env["TOKEN_A"], "ultima_archive"),
    "b": ("http://backend-b:21121", env["TOKEN_B"], "ultima_archive"),
    "c": ("http://backend-c:21121", env["TOKEN_C"], "ultima_c"),
}


def backend(node: str, path: str, body: dict | None = None) -> dict:
    url, token, _ = nodes[node]
    command = ["curl", "-fsS", "--max-time", "300", "-H", f"x-usr-admin-token: {token}"]
    if body is not None:
        command += ["-X", "POST", "-H", "Content-Type: application/json", "--data", json.dumps(body)]
    result = subprocess.run(
        [*compose, "exec", "-T", "backend", *command, f"{url}{path}"], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def eventually(check, what: str, seconds: int = 120):
    deadline = time.monotonic() + seconds
    while True:
        try:
            value = check()
            if value:
                return value
        except (AssertionError, subprocess.CalledProcessError, KeyError):
            if time.monotonic() > deadline:
                raise
        if time.monotonic() > deadline:
            raise SystemExit(f"Timed out waiting for {what}")
        time.sleep(3)


print("Setting up each backend")
for node, (_, _, database) in nodes.items():
    payload = {
        "database": {"host": "postgres", "port": 5432, "name": database, "username": "ultimascraper",
                     "password": env["POSTGRES_PASSWORD"]},
        "redis": {"host": "redis", "port": 6379, "db": 0, "password": env["REDIS_PASSWORD"], "enabled": True},
    }
    # As the wizard does: the database step prepares the schema.
    assert backend(node, "/api/v1/setup/test-database", payload["database"]).get("success") is True, node
    assert backend(node, "/api/v1/setup/complete", payload).get("success") is True, node

identities = {node: backend(node, "/api/v1/system/identity") for node in nodes}
print(json.dumps(identities, indent=2))
cluster = identities["a"]["cluster_id"]
assert cluster and identities["b"]["cluster_id"] == cluster, "a and b share a database, so one cluster"
assert identities["c"]["cluster_id"] and identities["c"]["cluster_id"] != cluster, "c has its own database"
assert [identities[n]["backend_id"] for n in "abc"] == ["node-a", "node-b", "node-c"]
assert identities["b"]["api_url"] == "http://backend-b:21121"


def registered() -> list[dict]:
    live = {entry["backend_id"]: entry for entry in backend("a", "/api/v1/system/backends")["backends"]}
    assert live.get("node-b", {}).get("cluster_id") == cluster, live
    return list(live.values())


print("Waiting for node-b's worker to register in Redis")
live = eventually(registered, "node-b in the Redis registry")
assert {entry["backend_id"]: entry["api_url"] for entry in live}["node-b"] == "http://backend-b:21121"

webui = httpx.Client(base_url=env["WEBUI"], headers={"origin": env["WEBUI"]}, timeout=60)
assert webui.post("/webui/api/v1/session/claim", json={"password": "cluster-acceptance"}).status_code == 204
added = webui.post(
    "/webui/api/v1/connections", json={"name": "node-c", "base_url": nodes["c"][0], "token": env["TOKEN_C"]}
)
assert added.status_code == 201, added.text

print("The WebUI suggests node-b and keeps node-c apart")
result = webui.get("/webui/api/v1/clusters").json()
clusters = {entry["cluster_id"]: entry for entry in result["clusters"]}
assert clusters[cluster]["connection_ids"] == ["default"], result
[suggestion] = clusters[cluster]["suggestions"]
assert (suggestion["backend_id"], suggestion["api_url"]) == ("node-b", "http://backend-b:21121"), suggestion
assert clusters[identities["c"]["cluster_id"]]["connection_ids"] == ["node-c"]

print("Adding node-b from the suggestion")
added = webui.post(
    "/webui/api/v1/connections",
    json={"name": "node-b", "base_url": suggestion["api_url"], "token": env["TOKEN_B"]},
)
assert added.status_code == 201, added.text
result = webui.get("/webui/api/v1/clusters").json()
clusters = {entry["cluster_id"]: entry for entry in result["clusters"]}
assert clusters[cluster]["connection_ids"] == ["default", "node-b"] and clusters[cluster]["suggestions"] == []
assert clusters[cluster]["conflicting_backend_ids"] == []
# The proxy reaches each member separately.
assert webui.get("/b/node-b/api/v1/system/identity").json()["backend_id"] == "node-b"

print("A stopped member stays in its cluster")
subprocess.run([*compose, "stop", "backend-b"], check=True, capture_output=True)
result = webui.get("/webui/api/v1/clusters").json()
member = next(entry for entry in result["members"] if entry["connection_id"] == "node-b")
assert member["reachable"] is False and member["identity"]["cluster_id"] == cluster, member
assert any(entry["cluster_id"] == cluster and "node-b" in entry["connection_ids"] for entry in result["clusters"])
print("Cluster acceptance passed")
PY
