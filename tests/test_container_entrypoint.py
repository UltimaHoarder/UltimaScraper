from __future__ import annotations

import os
from pathlib import Path
import subprocess


ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker" / "backend-entrypoint.sh"
SECRET_VARIABLES = (
    "USR_ADMIN_TOKEN",
    "USR_SECRET_KEY",
    "USR_SECRET_KEY_PREVIOUS",
    "ULTIMA_ARCHIVE_DATABASE_URL",
    "DATABASE_URL",
    "REDIS_PASSWORD",
)


def _base_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in SECRET_VARIABLES:
        environment.pop(name, None)
        environment.pop(f"{name}_FILE", None)
    environment.update(
        {
            "RUN_MODE": "api",
            "USR_ADMIN_TOKEN": "test-admin-token",
            "USR_SECRET_KEY": "test-secret-key",
            "USR_ENCRYPT_SECRETS": "true",
            "ULTIMA_ARCHIVE_DATABASE_URL": "postgresql+psycopg://test:test@postgres/ultima_archive",
            "REDIS_HOST": "redis.internal",
        }
    )
    return environment


def test_entrypoint_accepts_only_api_runtime() -> None:
    result = subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), "/bin/sh", "-c", 'test "$RUN_MODE" = api'],
        env=_base_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_api_entrypoint_rejects_worker_capable_runtime_without_leaking_secrets() -> (
    None
):
    environment = _base_environment()
    environment["RUN_MODE"] = "webui"

    result = subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), "/bin/true"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "api container cannot start" in result.stderr
    assert environment["USR_ADMIN_TOKEN"] not in result.stderr
    assert environment["ULTIMA_ARCHIVE_DATABASE_URL"] not in result.stderr


def test_api_entrypoint_rejects_legacy_backend_alias() -> None:
    environment = _base_environment()
    environment["RUN_MODE"] = "backend"

    result = subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), "/bin/true"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "api container cannot start" in result.stderr


def test_entrypoint_loads_docker_secret_files(tmp_path: Path) -> None:
    environment = _base_environment()
    expected = {
        "USR_ADMIN_TOKEN": "file-admin-token",
        "USR_SECRET_KEY": "file-secret-key",
        "ULTIMA_ARCHIVE_DATABASE_URL": "postgresql+psycopg://file:file@postgres/ultima_archive",
        "REDIS_PASSWORD": "file-redis-password",
    }
    for name, value in expected.items():
        environment.pop(name, None)
        secret_file = tmp_path / name.lower()
        secret_file.write_text(f"{value}\n", encoding="utf-8")
        environment[f"{name}_FILE"] = str(secret_file)

    checks = " && ".join(
        f'test "${{{name}}}" = "{value}"' for name, value in expected.items()
    )
    result = subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), "/bin/sh", "-c", checks],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_entrypoint_accepts_empty_redis_password_file(tmp_path: Path) -> None:
    environment = _base_environment()
    password_file = tmp_path / "redis-password"
    password_file.write_text("", encoding="utf-8")
    environment["REDIS_PASSWORD_FILE"] = str(password_file)

    result = subprocess.run(
        [
            "/bin/sh",
            str(ENTRYPOINT),
            "/bin/sh",
            "-c",
            'test -z "${REDIS_PASSWORD:-}"',
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_worker_entrypoint_accepts_only_worker_runtime() -> None:
    environment = _base_environment()
    environment.pop("USR_ADMIN_TOKEN")
    environment["USR_CONTAINER_ROLE"] = "worker"
    environment["RUN_MODE"] = "worker"

    result = subprocess.run(
        [
            "/bin/sh",
            str(ENTRYPOINT),
            "/bin/sh",
            "-c",
            'test "$RUN_MODE" = worker',
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _run(environment: dict[str, str], script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), "/bin/sh", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entrypoint_maps_deprecated_database_url_alias(tmp_path: Path) -> None:
    environment = _base_environment()
    url = environment.pop("ULTIMA_ARCHIVE_DATABASE_URL")
    alias_file = tmp_path / "database-url"
    alias_file.write_text(f"{url}\n", encoding="utf-8")
    environment["DATABASE_URL_FILE"] = str(alias_file)

    result = _run(
        environment,
        f'test "$ULTIMA_ARCHIVE_DATABASE_URL" = "{url}" && test -z "${{DATABASE_URL+set}}"',
    )

    assert result.returncode == 0, result.stderr
    assert "DATABASE_URL is deprecated" in result.stderr
    assert url not in result.stderr


def test_entrypoint_rejects_conflicting_database_urls() -> None:
    environment = _base_environment()
    environment["DATABASE_URL"] = "postgresql+psycopg://other:other@elsewhere/db"

    result = _run(environment, "true")

    assert result.returncode != 0
    assert "differ" in result.stderr
    assert environment["DATABASE_URL"] not in result.stderr


def test_entrypoint_builds_canonical_url_from_postgres_parts() -> None:
    environment = _base_environment()
    environment.pop("ULTIMA_ARCHIVE_DATABASE_URL")
    environment.update(
        POSTGRES_HOST="postgres",
        POSTGRES_PORT="5432",
        POSTGRES_USER="usr",
        POSTGRES_PASSWORD="p@ss",
        POSTGRES_DB="ultima_archive",
    )

    result = _run(environment, 'case "$ULTIMA_ARCHIVE_DATABASE_URL" in postgresql+psycopg://usr:*@postgres:5432/ultima_archive) ;; *) exit 1;; esac')

    assert result.returncode == 0, result.stderr


def test_entrypoint_generates_missing_secrets_once(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    environment = _base_environment()
    environment["USR_ADMIN_TOKEN"] = ""
    environment["USR_SECRET_KEY"] = ""
    environment["USR_GENERATED_SECRETS_DIR"] = str(secrets_dir)
    print_secrets = 'printf "%s %s" "$USR_ADMIN_TOKEN" "$USR_SECRET_KEY"'

    first = _run(environment, print_secrets)
    second = _run(environment, print_secrets)

    assert first.returncode == 0, first.stderr
    admin_token, secret_key = first.stdout.split(" ")
    assert len(admin_token) >= 32 and len(secret_key) >= 32
    assert admin_token != secret_key
    assert second.stdout == first.stdout
    assert (secrets_dir / "USR_ADMIN_TOKEN").read_text().strip() == admin_token
    assert (secrets_dir / "USR_ADMIN_TOKEN").stat().st_mode & 0o777 == 0o600
    assert secrets_dir.stat().st_mode & 0o777 == 0o700
    assert "Generated USR_ADMIN_TOKEN" in first.stderr
    assert admin_token not in first.stderr and secret_key not in first.stderr
    assert "Generated" not in second.stderr
    assert not [path for path in secrets_dir.iterdir() if path.name.startswith(".")]


def test_worker_entrypoint_shares_generated_secret_key(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    environment = _base_environment()
    environment["USR_SECRET_KEY"] = ""
    environment["USR_GENERATED_SECRETS_DIR"] = str(secrets_dir)
    api = _run(environment, 'printf "%s" "$USR_SECRET_KEY"')

    environment.pop("USR_ADMIN_TOKEN")
    environment["USR_CONTAINER_ROLE"] = "worker"
    environment["RUN_MODE"] = "worker"
    worker = _run(environment, 'printf "%s" "$USR_SECRET_KEY"')

    assert api.returncode == 0 and worker.returncode == 0, worker.stderr
    assert worker.stdout == api.stdout
    # The worker never needs, or creates, an admin token.
    assert not (secrets_dir / "USR_ADMIN_TOKEN").exists()


def test_entrypoint_keeps_configured_secrets(tmp_path: Path) -> None:
    environment = _base_environment()
    environment["USR_GENERATED_SECRETS_DIR"] = str(tmp_path / "secrets")

    result = _run(environment, 'test "$USR_ADMIN_TOKEN" = test-admin-token')

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "secrets").exists()


def test_entrypoint_rejects_env_example_placeholders(tmp_path: Path) -> None:
    for name, value in {
        "USR_ADMIN_TOKEN": "replace-with-a-long-random-token",
        "REDIS_PASSWORD": "replace-with-a-strong-redis-password",
        "ULTIMA_ARCHIVE_DATABASE_URL": "postgresql+psycopg://usr:replace-with-your-password@db/ultima_archive",
    }.items():
        environment = _base_environment()
        environment["USR_GENERATED_SECRETS_DIR"] = str(tmp_path / "secrets")
        environment[name] = value

        result = _run(environment, "true")

        assert result.returncode != 0
        assert f"{name} still has the .env.example placeholder" in result.stderr
        assert value not in result.stderr
