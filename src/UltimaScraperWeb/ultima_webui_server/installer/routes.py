"""The installer's API under /webui/api/v1/installs."""

from __future__ import annotations

from typing import Any

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import Auth
from ..version import own_version
from .images import docker_cli_available, local_releases
from .probe import UnsupportedHost
from .runner import (
    CheckServiceIn,
    DetectIn,
    Installer,
    InstallIn,
    OperationIn,
    RegisterExistingIn,
    _failure_message,
    in_container,
)
from .targets import CommandFailed, scan_host_key


class LocalReleaseOut(BaseModel):
    version: str
    architecture: str
    names: list[str]


class EnvironmentOut(BaseModel):
    # The release this WebUI is, the version a registry install suggests.
    version: str
    # Whether "this machine" can be installed onto without SSH.
    local_available: bool
    in_container: bool
    # Whether images can be copied from this server's Docker.
    copy_available: bool
    releases: list[LocalReleaseOut]


class HostKeyIn(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)


class HostKeyOut(BaseModel):
    algorithm: str
    fingerprint: str
    key: str


class DetectFactsOut(BaseModel):
    architecture: str
    os_name: str
    user: str
    home: str
    hostname: str
    docker_version: str | None
    compose_version: str | None
    docker_needs_sudo: bool
    sudo_mode: str
    memory_mb: int | None
    home_free_mb: int | None
    listening_ports: list[int]
    existing_projects: list[str]
    existing_install: dict[str, Any] | None
    services: dict[str, dict[str, Any]]
    local_images: list[LocalReleaseOut]
    warnings: list[str]


class DetectOut(BaseModel):
    facts: DetectFactsOut
    recommended_components: dict[str, str]
    needs_sudo_for: list[str]
    recommended_image_source: str
    recommended_version: str


class CheckServiceOut(BaseModel):
    reachable: bool
    kind: str
    host: str
    port: int
    message: str


class DatabaseStoreOut(BaseModel):
    host: str
    port: int
    name: str
    username: str
    password: str


class RedisStoreOut(BaseModel):
    host: str
    port: int
    db: int = 0
    password: str = ""


class ClusterStoresOut(BaseModel):
    available: bool
    cluster_id: str | None = None
    database: DatabaseStoreOut | None = None
    redis: RedisStoreOut | None = None
    source_backend_name: str | None = None
    secret_key: str | None = None
    settings_id: int | None = None
    backend_id: str | None = None
    api_url: str | None = None


class InstallStarted(BaseModel):
    id: str


class InstallEventOut(BaseModel):
    seq: int
    at: float
    kind: str
    message: str


class InstallOut(BaseModel):
    id: str
    name: str
    target: str
    state: str
    connection_id: str | None
    # install, repair, upgrade or uninstall.
    operation: str
    deployment_id: str | None
    events: list[InstallEventOut]
    # Store-only installs: the host, ports and generated passwords other hosts
    # use. Only while this server runs; the host's .env keeps them too.
    store_connection: dict[str, Any] | None = None


class DeploymentOut(BaseModel):
    id: str
    name: str
    target: str
    # Where it is and what runs there; no credentials.
    details: dict
    connection_id: str | None


def deployment_router(installer: Installer, auth: Auth) -> APIRouter:
    router = APIRouter(prefix="/webui/api/v1/deployments", dependencies=[Depends(auth.require)])

    @router.get("", response_model=list[DeploymentOut])
    def deployments() -> list[DeploymentOut]:
        return [
            DeploymentOut(
                id=record.id,
                name=record.name,
                target=record.target,
                details=record.details,
                connection_id=record.connection_id,
            )
            for record in installer.store.list_deployments()
        ]

    # Async so the operation's task is created on the server's event loop.
    @router.post("/{deployment_id}/operations", response_model=InstallStarted, status_code=202)
    async def operate(deployment_id: str, body: OperationIn, request: Request) -> InstallStarted:
        if body.action == "uninstall":
            auth.confirm_password(request, body.webui_password or "", "uninstall")
        return InstallStarted(id=installer.start_operation(deployment_id, body))

    return router


def install_router(installer: Installer, auth: Auth) -> APIRouter:
    router = APIRouter(prefix="/webui/api/v1/installs", dependencies=[Depends(auth.require)])

    @router.get("/environment", response_model=EnvironmentOut)
    async def environment() -> EnvironmentOut:
        releases = await local_releases()
        return EnvironmentOut(
            version=own_version(),
            local_available=installer.local_allowed,
            in_container=in_container(),
            copy_available=docker_cli_available() and bool(releases),
            releases=[
                LocalReleaseOut(version=r.version, architecture=r.architecture, names=list(r.names)) for r in releases
            ],
        )

    @router.get("/cluster-stores", response_model=ClusterStoresOut)
    async def cluster_stores(
        connection_id: str | None = None,
        target_is_remote: bool = False,
    ) -> ClusterStoresOut:
        result = await installer.get_cluster_stores(
            connection_id=connection_id,
            target_is_remote=target_is_remote,
        )
        return ClusterStoresOut.model_validate(result)

    @router.post("/host-key", response_model=HostKeyOut)
    async def host_key(body: HostKeyIn) -> HostKeyOut:
        try:
            key = await scan_host_key(body.host, body.port)
        except (OSError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach {body.host}:{body.port}: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"No SSH server answered: {exc}") from exc
        return HostKeyOut(algorithm=key.algorithm, fingerprint=key.fingerprint, key=key.openssh)

    @router.post("/detect", response_model=DetectOut)
    async def detect(body: DetectIn) -> DetectOut:
        try:
            result = await installer.detect(body, default_version=own_version() or "0.1.0")
        except HTTPException:
            raise
        except UnsupportedHost as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (asyncssh.HostKeyNotVerifiable, asyncssh.PermissionDenied, CommandFailed, OSError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=_failure_message(exc)) from exc
        return DetectOut.model_validate(result)

    @router.post("/check-service", response_model=CheckServiceOut)
    async def check_service_endpoint(body: CheckServiceIn) -> CheckServiceOut:
        try:
            result = await installer.check_target_service(body)
        except HTTPException:
            raise
        except (asyncssh.HostKeyNotVerifiable, asyncssh.PermissionDenied, CommandFailed, OSError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=_failure_message(exc)) from exc
        return CheckServiceOut.model_validate(result)

    @router.post("/register-existing", response_model=DeploymentOut)
    async def register_existing_endpoint(body: RegisterExistingIn) -> DeploymentOut:
        try:
            record = await installer.register_existing(body)
        except HTTPException:
            raise
        except (UnsupportedHost, asyncssh.HostKeyNotVerifiable, asyncssh.PermissionDenied, CommandFailed, OSError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=_failure_message(exc)) from exc
        return DeploymentOut(
            id=record.id,
            name=record.name,
            target=record.target,
            details=record.details,
            connection_id=record.connection_id,
        )

    # Async so the install task is created on the server's event loop.
    @router.post("", response_model=InstallStarted, status_code=202)
    async def start(body: InstallIn) -> InstallStarted:
        if not body.version:
            body = body.model_copy(update={"version": own_version() or "0.1.0"})
        return InstallStarted(id=installer.start(body))

    @router.get("/{install_id}", response_model=InstallOut)
    def status(install_id: str, after: int = 0) -> InstallOut:
        record = installer.store.get_install(install_id)
        if record is None:
            raise HTTPException(status_code=404, detail="No such install.")
        return InstallOut(
            id=record.id,
            name=record.name,
            target=record.target,
            state=record.state,
            connection_id=record.connection_id,
            operation=record.operation,
            deployment_id=record.deployment_id,
            events=[InstallEventOut(**vars(event)) for event in installer.store.install_events(install_id, after)],
            store_connection=installer.store_connection(install_id) if record.state == "succeeded" else None,
        )

    return router

