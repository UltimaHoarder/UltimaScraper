#!/usr/bin/env bash
# End-to-end installer check, with a WebUI server running on this machine and
# SSH hosts to install onto:
#
#   dind    A container with sshd and its own Docker daemon (Docker only
#           through sudo). Install, refusals, repair, upgrade, then uninstall
#           with its data.
#   ubuntu, fedora, alpine, arch
#           Containers without Docker. The installer installs Docker from the
#           distribution's packages, then the stack, then uninstalls it.
#   vm-arm64
#           The same on an Ubuntu arm64 virtual machine (full-system QEMU,
#           booted from the image scripts/performance/arm64_vm.py pins).
#           Containers cannot stand in here: an emulated Docker daemon cannot
#           start containers.
#   --remote USER@HOST[:PORT] --remote-key KEY
#           A real machine that already has Docker, which USER may use without
#           sudo; KEY is a private key it accepts. Runs the dind checks there.
#           Only what the test installs is touched, and it is all removed.
#
# Images are copied from this machine; VERSION must name images for the
# hosts' architecture (arm64 images for vm-arm64 or an arm64 machine).
# Everything created is removed afterwards.
#
# Usage: installer_acceptance.sh [VERSION] [--hosts dind,ubuntu,fedora,alpine,arch,vm-arm64]
#                                [--remote USER@HOST[:PORT] --remote-key KEY]
#   VERSION defaults to "acceptance"; --hosts defaults to dind,ubuntu, or to
#   none when --remote is given.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="acceptance"
HOSTS=""
REMOTE=""
REMOTE_KEY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts) HOSTS="$2"; shift 2 ;;
        --remote) REMOTE="$2"; shift 2 ;;
        --remote-key) REMOTE_KEY="$2"; shift 2 ;;
        -*) echo "Unknown option $1" >&2; exit 2 ;;
        *) VERSION="$1"; shift ;;
    esac
done
if [[ -z "$HOSTS" && -z "$REMOTE" ]]; then HOSTS="dind,ubuntu"; fi
if [[ -n "$REMOTE" && ! -f "$REMOTE_KEY" ]]; then
    echo "--remote needs --remote-key with a private key the host accepts" >&2
    exit 2
fi
NEXT_VERSION="$VERSION-next"
PYTHON="$ROOT_DIR/.venv/bin/python"
IMAGES=(backend worker)
TARGET_DIR="$ROOT_DIR/scripts/release/ssh-target"
host_names=()
if [[ -n "$HOSTS" ]]; then IFS=, read -r -a host_names <<<"$HOSTS"; fi

work="$(mktemp -d)"
hosts_file="$work/hosts"
webui_pid=""
vm_pid=""
containers=()
cleanup() {
    exit_code=$?
    if [[ -n "$webui_pid" ]]; then kill "$webui_pid" 2>/dev/null || true; fi
    if [[ -n "$vm_pid" ]]; then kill "$vm_pid" 2>/dev/null || true; wait "$vm_pid" 2>/dev/null || true; fi
    if [[ $exit_code -ne 0 && -f "$work/webui.log" ]]; then tail -n 40 "$work/webui.log" >&2; fi
    if [[ ${#containers[@]} -gt 0 ]]; then docker rm --force --volumes "${containers[@]}" >/dev/null 2>&1 || true; fi
    for image in "${IMAGES[@]}"; do docker image rm "ultimascraper-$image:$NEXT_VERSION" >/dev/null 2>&1 || true; done
    rm -rf -- "$work"
    exit "$exit_code"
}
trap cleanup EXIT

# The upgrade target: the same images under a new version.
for image in "${IMAGES[@]}"; do
    docker image inspect "ultimascraper-$image:$VERSION" >/dev/null
    docker tag "ultimascraper-$image:$VERSION" "ultimascraper-$image:$NEXT_VERSION"
done

ssh_options=(-q -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
host_fingerprints='for key in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$key"; done'

# One JSON line per host, for the checks below.
add_host() {
    "$PYTHON" -c 'import json, sys; print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2]))))' "$@" >>"$hosts_file"
}

deploy_password="$(openssl rand -hex 16)"

# Boots the arm64 VM from a throwaway overlay of the pinned image. The key is
# only for this script's own checks; the installer signs in with the password.
start_arm64_vm() {
    local base="$ROOT_DIR/.performance-simulation-arm64-current/base.img"
    local expected="63a93bd5a8d76e33b15ceb5daa3657bd79be804748051ab178e643b0f5da22e7"
    local vm="$work/vm" port
    if [[ ! -f "$base" ]]; then
        echo "Run scripts/performance/arm64_vm.py once to fetch the arm64 image" >&2
        return 1
    fi
    if [[ "$(sha256sum "$base" | cut -d' ' -f1)" != "$expected" ]]; then
        echo "The arm64 image checksum differs from the pinned release" >&2
        return 1
    fi
    mkdir -p "$vm"
    qemu-img create -q -f qcow2 -F qcow2 -b "$base" "$vm/os.qcow2" 24G
    ssh-keygen -q -t ed25519 -N "" -f "$vm/key"
    cat >"$vm/user-data" <<EOF
#cloud-config
users:
  - name: deploy
    shell: /bin/bash
    lock_passwd: false
    sudo: ALL=(ALL) ALL
    ssh_authorized_keys:
      - $(cat "$vm/key.pub")
chpasswd:
  expire: false
  users:
    - {name: deploy, password: $deploy_password, type: text}
ssh_pwauth: true
EOF
    printf 'instance-id: usr-installer-arm64\nlocal-hostname: usr-installer-arm64\n' >"$vm/meta-data"
    xorriso -as mkisofs -quiet -output "$vm/seed.iso" -volid cidata -joliet -rock \
        "$vm/user-data" "$vm/meta-data" 2>/dev/null
    port="$("$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
    qemu-system-aarch64 -machine virt -cpu max -smp 4 -m 4096 -nographic \
        -bios /usr/share/edk2/aarch64/QEMU_EFI.fd \
        -drive "if=virtio,format=qcow2,file=$vm/os.qcow2" \
        -drive "if=virtio,format=raw,file=$vm/seed.iso" \
        -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$port-:22" -device virtio-net-pci,netdev=net0 \
        >"$vm/console.log" 2>&1 </dev/null &
    vm_pid=$!
    # An emulated boot and cloud-init take minutes.
    for _ in $(seq 240); do
        if ssh "${ssh_options[@]}" -i "$vm/key" -p "$port" deploy@127.0.0.1 \
            'test -f /var/lib/cloud/instance/boot-finished' 2>/dev/null; then
            add_host name vm-arm64 kind vm docker no address 127.0.0.1 port "$port" user deploy \
                home /home/deploy check_key "$vm/key" \
                fingerprints "$(ssh "${ssh_options[@]}" -i "$vm/key" -p "$port" deploy@127.0.0.1 "$host_fingerprints" | awk '{print $2}' | paste -sd' ')"
            return 0
        fi
        sleep 5
    done
    echo "The arm64 VM did not come up; see its console log:" >&2
    tail -n 20 "$vm/console.log" >&2
    return 1
}

for name in "${host_names[@]}"; do
    if [[ "$name" == vm-arm64 ]]; then
        start_arm64_vm
        continue
    fi
    case "$name" in
        dind) dockerfile="$TARGET_DIR/Dockerfile" ;;
        ubuntu) dockerfile="$TARGET_DIR/Dockerfile.no-docker" ;;
        fedora|alpine|arch) dockerfile="$TARGET_DIR/Dockerfile.$name" ;;
        *) echo "Unknown host $name" >&2; exit 2 ;;
    esac
    docker build --quiet --build-arg DEPLOY_PASSWORD="$deploy_password" \
        --file "$dockerfile" --tag "usr-ssh-target:$name" "$TARGET_DIR" >/dev/null
    container="usr-installer-acceptance-$name-$$"
    containers+=("$container")
    if [[ "$name" == dind ]]; then
        docker run --detach --privileged --name "$container" --publish 127.0.0.1::22 "usr-ssh-target:$name" >/dev/null
        for _ in $(seq 60); do
            if docker exec "$container" docker info >/dev/null 2>&1; then break; fi
            sleep 2
        done
        docker exec "$container" docker info >/dev/null
    else
        # Docker's data needs a real filesystem, not the container's overlay.
        docker run --detach --privileged --name "$container" --volume /var/lib/docker \
            --publish 127.0.0.1::22 "usr-ssh-target:$name" >/dev/null
    fi
    add_host name "$name" kind container container "$container" docker "$([[ $name == dind ]] && echo yes || echo no)" \
        address 127.0.0.1 port "$(docker port "$container" 22/tcp | head -n 1 | awk -F: '{print $NF}')" \
        user deploy home /home/deploy \
        fingerprints "$(docker exec "$container" sh -c "$host_fingerprints" | awk '{print $2}' | paste -sd' ')"
done

if [[ -n "$REMOTE" ]]; then
    remote_user="${REMOTE%@*}"
    remote_address="${REMOTE#*@}"
    remote_port=22
    if [[ "$remote_address" == *:* ]]; then remote_port="${remote_address##*:}"; remote_address="${remote_address%:*}"; fi
    remote=(ssh "${ssh_options[@]}" -i "$REMOTE_KEY" -p "$remote_port" "$remote_user@$remote_address")
    if [[ -n "$("${remote[@]}" 'ls -d ~/ultimascraper 2>/dev/null')" ]]; then
        echo "$REMOTE already has ~/ultimascraper; the test will not touch it" >&2
        exit 1
    fi
    add_host name remote kind remote docker yes address "$remote_address" port "$remote_port" \
        user "$remote_user" home "$("${remote[@]}" 'printf %s "$HOME"')" check_key "$REMOTE_KEY" \
        fingerprints "$("${remote[@]}" "$host_fingerprints" | awk '{print $2}' | paste -sd' ')"
fi

webui_port="$("$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
USR_WEBUI_DATA_DIR="$work/data" USR_WEBUI_PORT="$webui_port" \
    "$PYTHON" -m ultima_webui_server >"$work/webui.log" 2>&1 &
webui_pid=$!
for _ in $(seq 30); do
    if curl -fsS "http://127.0.0.1:$webui_port/health" >/dev/null 2>&1; then break; fi
    sleep 1
done

WEBUI="http://127.0.0.1:$webui_port" VERSION="$VERSION" NEXT_VERSION="$NEXT_VERSION" \
DEPLOY_PASSWORD="$deploy_password" HOSTS_FILE="$hosts_file" \
    "$PYTHON" - <<'PY'
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import httpx

webui = os.environ["WEBUI"]
password = os.environ["DEPLOY_PASSWORD"]
client = httpx.Client(base_url=webui, headers={"origin": webui}, timeout=60)


def check(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, f"{response.request.url}: {response.status_code} {response.text}"
    return response.json() if response.content else {}


def follow(run_id: str) -> dict:
    after, events = 0, []
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        status = check(client.get(f"/webui/api/v1/installs/{run_id}", params={"after": after}))
        for event in status["events"]:
            print(f"  [{event['kind']}] {event['message']}", flush=True)
            events.append(event)
            after = event["seq"]
        if status["state"] != "running":
            status["events"] = events
            assert password not in json.dumps(events), "a password reached the log"
            return status
        time.sleep(2)
    raise SystemExit("run did not finish in 30 minutes")


def credentials(host: dict) -> dict:
    """What the installer signs in with: the test password, or a remote's key."""
    if host["kind"] == "remote":
        return {"private_key": Path(host["check_key"]).read_text()}
    return {"password": password, "sudo_password": password}


def on_host(host: dict, command: str) -> str:
    """Runs a check on the host: as root in containers and the VM, as the user on a remote."""
    if host["kind"] == "container":
        argv, stdin = ["docker", "exec", host["container"], "sh", "-c", command], None
    else:
        remote = command if host["kind"] == "remote" else f"sudo -S -p '' sh -c {shlex.quote(command)}"
        argv = ["ssh", "-q", "-i", host["check_key"], "-p", host["port"], "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                f"{host['user']}@{host['address']}", remote]
        stdin = None if host["kind"] == "remote" else password + "\n"
    return subprocess.run(argv, input=stdin, check=True, capture_output=True, text=True).stdout


def host_key(host: dict) -> str:
    key = check(client.post("/webui/api/v1/installs/host-key", json={"host": host["address"], "port": int(host["port"])}))
    assert key["fingerprint"] in host["fingerprints"].split(), key
    return key["key"]


def install(host: dict, name: str, accepted_key: str, **extra) -> dict:
    body = {
        "name": name,
        "version": os.environ["VERSION"],
        "image_source": "copy",
        "target": {
            "kind": "ssh",
            "host": host["address"],
            "port": int(host["port"]),
            "username": host["user"],
            "host_key": accepted_key,
            **credentials(host),
        },
        **extra,
    }
    return follow(check(client.post("/webui/api/v1/installs", json=body), 202)["id"])


def operate(host: dict, deployment_id: str, action: str, **extra) -> dict:
    body = {"action": action, "credentials": credentials(host), **extra}
    run = check(client.post(f"/webui/api/v1/deployments/{deployment_id}/operations", json=body), 202)
    return follow(run["id"])


def connection_works(connection_id: str) -> None:
    assert check(client.post(f"/webui/api/v1/connections/{connection_id}/test"))["authenticated"]
    assert check(client.get(f"/b/{connection_id}/api/v1/setup/status"))["is_configured"] is False


def deployment_for(connection_id: str) -> dict:
    [deployment] = [d for d in check(client.get("/webui/api/v1/deployments")) if d["connection_id"] == connection_id]
    return deployment


def with_docker(host: dict) -> None:
    """Install, refusals, repair, upgrade, uninstall with data, on a host that has Docker."""
    name, home = host["name"], host["home"]
    project = "usr-acceptance-target"

    print(f"{name}: install onto a host with Docker")
    key = host_key(host)
    result = install(host, "Acceptance target", key)
    assert result["state"] == "succeeded", result["state"]
    connection_id = result["connection_id"]
    connection_works(connection_id)
    deployment = deployment_for(connection_id)
    assert deployment["details"]["version"] == os.environ["VERSION"]
    assert "permitopen" in on_host(host, f"cat {home}/.ssh/authorized_keys")

    print(f"{name}: refuse a second install into the same folder")
    again = install(host, "Acceptance target", key)
    assert again["state"] == "failed" and "already holds an install" in again["events"][-1]["message"], again

    print(f"{name}: refuse a host key the user did not accept")
    other_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK0wmN/Cr3JXqmLW7u+g9pTh+wyqDHpSQEIQczXkVx9q"
    wrong = install(host, "Wrong key", other_key)
    assert wrong["state"] == "failed" and "not the one you accepted" in wrong["events"][-1]["message"], wrong

    print(f"{name}: repair")
    assert operate(host, deployment["id"], "repair")["state"] == "succeeded"

    print(f"{name}: upgrade")
    upgraded = operate(host, deployment["id"], "upgrade", version=os.environ["NEXT_VERSION"])
    assert upgraded["state"] == "succeeded", upgraded["state"]
    assert f"USR_VERSION={os.environ['NEXT_VERSION']}" in on_host(host, f"cat {home}/ultimascraper/.env")
    assert deployment_for(connection_id)["details"]["version"] == os.environ["NEXT_VERSION"]
    connection_works(connection_id)

    print(f"{name}: uninstall, deleting its data")
    removed = operate(host, deployment["id"], "uninstall", delete_data=True)
    assert removed["state"] == "succeeded", removed["state"]
    assert not on_host(host, f"docker ps -aq --filter label=com.docker.compose.project={project}").strip()
    assert not on_host(host, f"docker volume ls -q --filter label=com.docker.compose.project={project}").strip()
    assert on_host(host, f"test -e {home}/ultimascraper && echo present || echo gone").strip() == "gone"
    assert "ultimascraper-webui" not in on_host(host, f"cat {home}/.ssh/authorized_keys")
    assert not [d for d in check(client.get("/webui/api/v1/deployments")) if d["connection_id"] == connection_id]
    assert connection_id not in [c["id"] for c in check(client.get("/webui/api/v1/connections"))]


def without_docker(host: dict) -> None:
    """Refuse, install Docker and the stack, then uninstall keeping data."""
    name = host["name"]
    label = f"No Docker {name}"
    project = f"usr-no-docker-{name}"

    print(f"{name}: refuse to install without Docker unless asked")
    key = host_key(host)
    missing = install(host, label, key)
    assert missing["state"] == "failed" and "Docker Engine is not available" in missing["events"][-1]["message"], missing

    print(f"{name}: install Docker from the distribution's packages, then the stack")
    fresh = install(host, label, key, install_docker=True)
    assert fresh["state"] == "succeeded", fresh["state"]
    assert any(event["message"] == "Installing Docker" for event in fresh["events"])
    connection_works(fresh["connection_id"])
    deployment = deployment_for(fresh["connection_id"])

    print(f"{name}: uninstall, keeping its data")
    kept = operate(host, deployment["id"], "uninstall", delete_data=False)
    assert kept["state"] == "succeeded", kept["state"]
    assert on_host(host, f"docker volume ls -q --filter label=com.docker.compose.project={project}").strip()
    # Stop Docker's containers so removing the host does not wait on them.
    on_host(host, "docker ps -q | xargs -r docker stop >/dev/null 2>&1 || true")


hosts = [json.loads(line) for line in open(os.environ["HOSTS_FILE"])]
check(client.post("/webui/api/v1/session/claim", json={"password": "acceptance-webui-password"}), 204)
for host in hosts:
    (with_docker if host["docker"] == "yes" else without_docker)(host)
print("Installer acceptance passed:", ", ".join(host["name"] for host in hosts))
PY
