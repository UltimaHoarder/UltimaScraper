from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

# Job building must not open a site database; tasks pass through unexpanded.
pytestmark = pytest.mark.usefixtures("no_site_databases")


def _submitter_manifest(
    plugin_id: str = "remote-submitter",
    **overrides: Any,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "plugin_id": plugin_id,
        "plugin_version": "1.0.0",
        "display_name": "Remote Submitter",
        "description": "Submit remote work declaratively.",
        "usr_compatibility": ">=0.1.0",
        "capabilities": ["remote.jobs.submit"],
        "remote_delegation": {
            "integration_id": "remote-submit",
            "role": "submitter",
            "external_system_url": "https://example.com",
            "auth": {"method": "api_key", "header_name": "X-API-Key"},
            "operations": {
                "submission": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/submit",
                    "request_mapping": {
                        "body": {
                            "job_type": {"source_path": "payload.task.type"},
                            "payload": {"source_path": "payload.task.payload"},
                            "correlation_id": {"source_path": "runtime.correlation_id"},
                            "idempotency_key": {
                                "source_path": "runtime.idempotency_key"
                            },
                        }
                    },
                    "response_mapping": {
                        "external_job_id_path": "result.id",
                        "remote_status_path": "result.state",
                    },
                }
            },
            "callbacks": {"inbound": []},
        },
    }
    manifest.update(overrides)
    return manifest


def _executor_manifest(
    plugin_id: str = "remote-executor",
    **overrides: Any,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "plugin_id": plugin_id,
        "plugin_version": "1.0.0",
        "display_name": "Remote Executor",
        "description": "Execute remote work declaratively.",
        "usr_compatibility": ">=0.1.0",
        "capabilities": [
            "webhooks.register",
            "remote.jobs.execute",
            "remote.callbacks.receive",
        ],
        "callbacks": [
            {"handler_id": "on-progress", "auth_method": "hmac"},
            {"handler_id": "on-complete", "auth_method": "hmac"},
        ],
        "remote_delegation": {
            "integration_id": "remote-exec",
            "role": "executor",
            "external_system_url": "https://example.com",
            "auth": {"method": "api_key", "header_name": "X-API-Key"},
            "operations": {
                "claim": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/claim",
                    "request_mapping": {
                        "body": {
                            "worker_id": {"source_path": "payload.worker_id"},
                            "worker_name": {"source_path": "payload.worker_name"},
                        }
                    },
                    "response_mapping": {
                        "external_job_id_path": "id",
                        "remote_status_path": "status",
                    },
                },
                "complete": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/complete/{external_job_id}",
                    "request_mapping": {
                        "path_params": {
                            "external_job_id": {
                                "source_path": "runtime.external_job_id"
                            },
                        },
                        "body": {
                            "worker_id": {"source_path": "runtime.worker_id"},
                            "result": {"source_path": "payload"},
                        },
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
            },
            "callbacks": {
                "inbound": [
                    {
                        "handler_id": "on-progress",
                        "extract": {
                            "lifecycle_event": {"literal": "progress"},
                            "correlation_id": {
                                "source_path": "callback.body.correlation_id"
                            },
                            "external_job_id": {"source_path": "callback.body.job_id"},
                            "progress": {"source_path": "callback.body.progress"},
                        },
                    },
                    {
                        "handler_id": "on-complete",
                        "extract": {
                            "lifecycle_event": {"literal": "completed"},
                            "correlation_id": {
                                "source_path": "callback.body.correlation_id"
                            },
                            "external_job_id": {"source_path": "callback.body.job_id"},
                            "result": {"source_path": "callback.body.result"},
                        },
                    },
                ]
            },
            "executor_mapping": {
                "remote_job_type_path": "job_type",
                "remote_payload_path": "payload",
                "local_job_name_template": "Remote {{ remote_job_type }}",
                "task_bindings": [
                    {
                        "remote_match": {"job_type": "api_command"},
                        "local_task_type": "api_command",
                        "payload_mapping": {
                            "site_name": {"literal": "OnlyFans"},
                            "command": {"source_path": "remote_payload.command"},
                            "args": {"source_path": "remote_payload.args"},
                        },
                    }
                ],
            },
        },
    }
    manifest.update(overrides)
    return manifest


def _workflow_submitter_manifest(
    plugin_id: str = "workflow-submit",
) -> dict[str, Any]:
    manifest = _submitter_manifest(plugin_id=plugin_id)
    manifest["capabilities"] = ["remote.jobs.submit", "auth.credentials.export"]
    remote = manifest["remote_delegation"]
    remote["auth_export"] = {
        "site_path": "payload.site",
        "auth_id_path": "payload.auth_id",
        "runtime_key": "auth_bundle",
    }
    remote["operations"]["submission"]["request_mapping"]["body"] = {
        "job_type": {"literal": "scrape_download_workflow"},
        "payload": {
            "site": {"source_path": "payload.site"},
            "username": {"source_path": "payload.username"},
            "tasks": {"source_path": "payload.tasks"},
            "auth_bundle": {"source_path": "runtime.auth_bundle"},
        },
        "correlation_id": {"source_path": "runtime.correlation_id"},
        "idempotency_key": {"source_path": "runtime.idempotency_key"},
    }
    return manifest


def _workflow_executor_manifest(
    plugin_id: str = "workflow-executor",
) -> dict[str, Any]:
    manifest = _executor_manifest(plugin_id=plugin_id)
    manifest["capabilities"] = [
        "webhooks.register",
        "remote.jobs.execute",
        "remote.callbacks.receive",
        "auth.credentials.import",
    ]
    remote = manifest["remote_delegation"]
    remote["auth_import"] = {
        "bundle_path": "payload.auth_bundle",
        "site_path": "payload.site",
        "username_path": "payload.username",
        "user_id_path": "payload.auth_bundle.id",
        "runtime_key": "imported_auth_id",
    }
    remote["executor_mapping"] = {
        "remote_job_type_path": "job_type",
        "remote_payload_path": "payload",
        "remote_tasks_path": "payload.tasks",
        "local_job_name_template": "Workflow {{ remote_payload.username }}",
        "task_bindings": [
            {
                "remote_match": {
                    "job_type": "scrape_download_workflow",
                    "kind": "scrape",
                },
                "local_task_type": "scrape",
                "task_alias": {"source_path": "remote_task.alias"},
                "depends_on_aliases": {"source_path": "remote_task.depends_on_aliases"},
                "payload_mapping": {
                    "site_name": {"source_path": "remote_task.site_name"},
                    "user_id": {"source_path": "remote_task.user_id"},
                    "user_username": {"source_path": "remote_task.user_username"},
                    "content_type": {"source_path": "remote_task.content_type"},
                    "auth_id": {"source_path": "runtime.imported_auth_id"},
                    "rescrape_existing": {
                        "source_path": "remote_task.rescrape_existing"
                    },
                    "download_media": {"literal": False},
                },
            },
            {
                "remote_match": {
                    "job_type": "scrape_download_workflow",
                    "kind": "download",
                },
                "local_task_type": "download",
                "task_alias": {"source_path": "remote_task.alias"},
                "depends_on_aliases": {"source_path": "remote_task.depends_on_aliases"},
                "payload_mapping": {
                    "site_name": {"source_path": "remote_task.site_name"},
                    "user_id": {"source_path": "remote_task.user_id"},
                    "user_username": {"source_path": "remote_task.user_username"},
                    "content_type": {"source_path": "remote_task.content_type"},
                    "auth_id": {"source_path": "runtime.imported_auth_id"},
                },
            },
        ],
    }
    return manifest


def _enable_plugin(platform: Any, manifest: dict[str, Any]) -> None:
    platform.create_plugin(manifest)
    platform.approve_plugin(manifest["plugin_id"])
    platform.enable_plugin(manifest["plugin_id"])


class TestDeclarativeRuntimeValidation:
    def test_manifest_rejects_unknown_executable_fields(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _submitter_manifest(runtime_code={"entrypoint": "evil.py"})
        with pytest.raises(Exception, match="runtime_code"):
            load_manifest_from_dict(data)

    def test_non_http_operation_transport_is_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _submitter_manifest(
            remote_delegation={
                "integration_id": "remote-submit",
                "role": "submitter",
                "external_system_url": "https://example.com",
                "operations": {
                    "submission": {
                        "transport": "websocket",
                        "method": "POST",
                        "endpoint": "/submit",
                    }
                },
                "callbacks": {"inbound": []},
            },
        )
        with pytest.raises(Exception, match="http"):
            load_manifest_from_dict(data)


class TestDeclarativeRuntimePlatform:
    def test_backend_manager_find_account_matches_auth_user_id_or_row_id(self) -> None:
        from ultima_scraper_backend.manager import BackendManager

        class FakeAccount:
            def __init__(self) -> None:
                self.id = 12
                self.user_id = 77
                self.updated_at = None
                self.created_at = None

        class FakeSession:
            def __init__(self) -> None:
                self.seen_statement: str | None = None
                self.expunge_calls: list[FakeAccount] = []

            def exec(self, statement: Any) -> list[FakeAccount]:
                self.seen_statement = str(statement)
                return [FakeAccount()]

            def expunge(self, account: FakeAccount) -> None:
                self.expunge_calls.append(account)

        fake_session = FakeSession()
        manager = BackendManager.__new__(BackendManager)

        @contextlib.contextmanager
        def fake_site_session(site: str) -> Any:
            assert site == "onlyfans"
            yield fake_session

        manager._site_session = fake_site_session  # type: ignore[method-assign]

        account = manager._find_account("onlyfans", 77)

        assert account is not None
        assert account.user_id == 77
        assert fake_session.seen_statement is not None
        assert "user_auths.user_id" in fake_session.seen_statement
        assert "user_auths.id" in fake_session.seen_statement
        assert " OR " in fake_session.seen_statement
        assert len(fake_session.expunge_calls) == 1

    def test_remote_submission_maps_request_and_parses_external_job_id_and_status(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import HTTPResponse, PluginPlatform

        calls: list[dict[str, Any]] = []

        async def http_request(
            method: str,
            url: str,
            payload: bytes | None,
            headers: dict[str, str],
            *,
            timeout: float = 30.0,
        ) -> HTTPResponse:
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "payload": json.loads((payload or b"{}").decode("utf-8")),
                    "headers": headers,
                }
            )
            return HTTPResponse(
                status_code=201,
                body=json.dumps(
                    {"result": {"id": "remote-job-123", "state": "queued"}}
                ).encode("utf-8"),
            )

        platform = PluginPlatform(tmp_path, http_request=http_request)
        manifest = _submitter_manifest()
        _enable_plugin(platform, manifest)

        submission = platform.submit_delegated_job(
            "remote-submitter",
            {
                "task": {
                    "type": "scrape_and_download",
                    "payload": {"site": "OnlyFans", "username": "alice"},
                }
            },
        )
        result = asyncio.run(
            platform.execute_remote_submission(
                submission,
                idempotency_key="idem-123",
            )
        )

        assert result["external_job_id"] == "remote-job-123"
        stored = platform.get_runtime_correlation(result["correlation_id"])
        assert stored is not None
        assert stored["external_job_id"] == "remote-job-123"
        assert stored["remote_status"] == "queued"
        assert calls[0]["url"] == "https://example.com/submit"
        assert calls[0]["payload"]["job_type"] == "scrape_and_download"
        assert calls[0]["payload"]["payload"] == {
            "site": "OnlyFans",
            "username": "alice",
        }
        assert calls[0]["payload"]["idempotency_key"] == "idem-123"
        assert calls[0]["payload"]["correlation_id"] == result["correlation_id"]

    def test_remote_submission_exports_auth_bundle_server_side_and_redacts_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import HTTPResponse, PluginPlatform

        class FakeAccount:
            id = 77
            user_id = 77
            username = "auth-owner"
            user_agent = "ua"
            email = ""
            password = ""
            cookie = "cookie-value"
            x_bc = "xbc-value"
            authorization = ""
            site = "onlyfans"
            proxy_id = None

        class FakeBackendManager:
            def _find_account(self, site: str, account_id: int) -> FakeAccount | None:
                assert site == "onlyfans"
                assert account_id == 77
                return FakeAccount()

            @staticmethod
            def _build_auth_payload(account: FakeAccount, site: str) -> dict[str, Any]:
                assert site == "onlyfans"
                return {
                    "id": account.user_id,
                    "username": account.username,
                    "user_agent": account.user_agent,
                    "cookie": account.cookie,
                    "x_bc": account.x_bc,
                }

        monkeypatch.setattr(
            "ultima_scraper_backend.api.dependencies.get_backend_manager",
            lambda: FakeBackendManager(),
        )

        calls: list[dict[str, Any]] = []

        async def http_request(
            method: str,
            url: str,
            payload: bytes | None,
            headers: dict[str, str],
            *,
            timeout: float = 30.0,
        ) -> HTTPResponse:
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "payload": json.loads((payload or b"{}").decode("utf-8")),
                    "headers": headers,
                }
            )
            return HTTPResponse(
                status_code=201,
                body=json.dumps(
                    {"result": {"id": "remote-job-777", "state": "queued"}}
                ).encode("utf-8"),
            )

        platform = PluginPlatform(tmp_path, http_request=http_request)
        manifest = _workflow_submitter_manifest()
        _enable_plugin(platform, manifest)

        submission = platform.submit_delegated_job(
            "workflow-submit",
            {
                "site": "onlyfans",
                "username": "alice",
                "auth_id": 77,
                "tasks": [{"kind": "scrape", "alias": "scrape_posts"}],
            },
        )
        result = asyncio.run(
            platform.execute_remote_submission(
                submission,
                idempotency_key="idem-workflow-1",
            )
        )

        outbound_payload = calls[0]["payload"]["payload"]
        assert outbound_payload["auth_bundle"]["cookie"] == "cookie-value"
        assert outbound_payload["auth_bundle"]["x_bc"] == "xbc-value"

        stored = platform.get_remote_submission(result["correlation_id"])
        assert stored is not None
        assert stored["last_outbound_command"]["payload"]["payload"]["auth_bundle"] == {
            "redacted": True
        }

    def test_build_native_job_from_remote_supports_alias_dependencies_and_runtime_auth(
        self,
    ) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict
        from ultima_scraper_backend.plugin_system.mapping import build_native_job_from_remote

        manifest = load_manifest_from_dict(_workflow_executor_manifest())
        assert manifest.remote_delegation is not None
        assert manifest.remote_delegation.executor_mapping is not None

        job, tasks = build_native_job_from_remote(
            plugin_id="workflow-executor",
            correlation_id="corr-123",
            external_job_id="remote-job-123",
            executor_mapping=manifest.remote_delegation.executor_mapping,
            remote_message={
                "job_type": "scrape_download_workflow",
                "payload": {
                    "username": "alice",
                    "tasks": [
                        {
                            "kind": "scrape",
                            "alias": "scrape_posts",
                            "site_name": "OnlyFans",
                            "user_id": 123,
                            "user_username": "alice",
                            "content_type": "Posts",
                            "rescrape_existing": True,
                        },
                        {
                            "kind": "download",
                            "alias": "download_posts",
                            "depends_on_aliases": ["scrape_posts"],
                            "site_name": "OnlyFans",
                            "user_id": 123,
                            "user_username": "alice",
                            "content_type": "Posts",
                        },
                    ],
                },
            },
            runtime_context={"imported_auth_id": 9001},
        )

        assert job.name == "Workflow alice"
        assert len(tasks) == 2
        assert tasks[0].auth_id == 9001
        assert tasks[1].auth_id == 9001
        assert tasks[1].depends_on == [tasks[0].task_id]

    def test_callback_request_verification_uses_hmac_secret(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(
            plugin_id="callback-plugin",
            remote_delegation={
                **_executor_manifest(plugin_id="callback-plugin")["remote_delegation"],
                "integration_id": "callback-exec",
            },
        )
        _enable_plugin(platform, manifest)

        payload = json.dumps({"job_id": "remote-1", "progress": 50}).encode("utf-8")
        signature = platform.secrets.sign_payload(
            "callback-plugin",
            "callback",
            "on-progress",
            payload,
        )
        assert signature is not None

        platform.verify_remote_callback_request(
            "callback-plugin",
            "on-progress",
            raw_body=payload,
            headers={"X-Plugin-Signature": f"sha256={signature}"},
        )

        with pytest.raises(PermissionError, match="signature"):
            platform.verify_remote_callback_request(
                "callback-plugin",
                "on-progress",
                raw_body=payload,
                headers={"X-Plugin-Signature": "sha256=bad"},
            )

    def test_callback_request_verification_accepts_usr_signature_header(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(
            plugin_id="callback-plugin",
            remote_delegation={
                **_executor_manifest(plugin_id="callback-plugin")["remote_delegation"],
                "integration_id": "callback-exec",
            },
        )
        _enable_plugin(platform, manifest)

        payload = json.dumps({"job_id": "remote-1", "progress": 50}).encode("utf-8")
        signature = platform.secrets.sign_payload(
            "callback-plugin",
            "callback",
            "on-progress",
            payload,
        )
        assert signature is not None

        platform.verify_remote_callback_request(
            "callback-plugin",
            "on-progress",
            raw_body=payload,
            headers={"X-USR-Signature": f"sha256={signature}"},
        )

    def test_callback_registration_posts_generated_urls_and_secrets(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import HTTPResponse, PluginPlatform

        calls: list[dict[str, Any]] = []

        async def http_request(
            method: str,
            url: str,
            payload: bytes | None,
            headers: dict[str, str],
            *,
            timeout: float = 30.0,
        ) -> HTTPResponse:
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "payload": json.loads((payload or b"{}").decode("utf-8")),
                    "headers": headers,
                }
            )
            return HTTPResponse(status_code=204, body=b"")

        platform = PluginPlatform(
            tmp_path,
            http_request=http_request,
            public_base_url="https://control.example.com/api/v1",
        )
        manifest = _executor_manifest(
            plugin_id="registration-plugin",
            remote_delegation={
                **_executor_manifest(plugin_id="registration-plugin")[
                    "remote_delegation"
                ],
                "integration_id": "registration-exec",
                "callback_registration": {
                    "endpoint": "/register-callbacks",
                    "method": "POST",
                    "lifecycle_events": ["progress", "completed"],
                },
            },
        )
        _enable_plugin(platform, manifest)

        result = asyncio.run(platform.re_register_callbacks("registration-plugin"))

        assert result["registered"] is True
        assert calls[0]["url"] == "https://example.com/register-callbacks"
        callback_entries = calls[0]["payload"]["callbacks"]
        assert callback_entries[0]["url"].startswith(
            "https://control.example.com/api/v1/plugins/registration-plugin/"
        )
        assert callback_entries[0]["secret"]

    def test_named_auth_scope_is_used_for_http_operation_headers(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import HTTPResponse, PluginPlatform

        calls: list[dict[str, Any]] = []

        async def http_request(
            method: str,
            url: str,
            payload: bytes | None,
            headers: dict[str, str],
            *,
            timeout: float = 30.0,
        ) -> HTTPResponse:
            calls.append({"method": method, "url": url, "headers": headers})
            return HTTPResponse(
                status_code=201,
                body=json.dumps(
                    {"result": {"id": "remote-job-999", "state": "queued"}}
                ).encode("utf-8"),
            )

        platform = PluginPlatform(tmp_path, http_request=http_request)
        manifest = _submitter_manifest(
            plugin_id="scoped-submit",
            remote_delegation={
                **_submitter_manifest(plugin_id="scoped-submit")["remote_delegation"],
                "integration_id": "scoped-submit",
                "auth_scopes": {
                    "public_api": {"method": "api_key", "header_name": "X-API-Key"},
                    "worker_api": {
                        "method": "api_key",
                        "header_name": "X-USR-Worker-Token",
                    },
                },
                "operations": {
                    "submission": {
                        **_submitter_manifest(plugin_id="scoped-submit")[
                            "remote_delegation"
                        ]["operations"]["submission"],
                        "auth_scope": "public_api",
                    }
                },
            },
        )
        _enable_plugin(platform, manifest)
        platform.set_secret(
            "scoped-submit", "remote_auth", "public_api", "public-key-123"
        )
        platform.set_secret(
            "scoped-submit", "remote_auth", "worker_api", "worker-key-456"
        )

        submission = platform.submit_delegated_job(
            "scoped-submit",
            {
                "task": {
                    "type": "scrape_and_download",
                    "payload": {"site": "OnlyFans", "username": "alice"},
                }
            },
        )
        asyncio.run(platform.execute_remote_submission(submission))

        assert calls[0]["headers"]["X-API-Key"] == "public-key-123"
        assert "X-USR-Worker-Token" not in calls[0]["headers"]

    def test_callback_registration_uses_its_named_auth_scope(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import HTTPResponse, PluginPlatform

        calls: list[dict[str, Any]] = []

        async def http_request(
            method: str,
            url: str,
            payload: bytes | None,
            headers: dict[str, str],
            *,
            timeout: float = 30.0,
        ) -> HTTPResponse:
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "payload": json.loads((payload or b"{}").decode("utf-8")),
                    "headers": headers,
                }
            )
            return HTTPResponse(status_code=201, body=b"{}")

        platform = PluginPlatform(
            tmp_path,
            http_request=http_request,
            public_base_url="https://control.example.com/api/v1",
        )
        manifest = _executor_manifest(
            plugin_id="scoped-registration",
            remote_delegation={
                **_executor_manifest(plugin_id="scoped-registration")[
                    "remote_delegation"
                ],
                "integration_id": "scoped-registration",
                "auth_scopes": {
                    "public_api": {"method": "api_key", "header_name": "X-API-Key"},
                    "worker_api": {
                        "method": "api_key",
                        "header_name": "X-USR-Worker-Token",
                    },
                },
                "operations": {
                    "claim": {
                        **_executor_manifest(plugin_id="scoped-registration")[
                            "remote_delegation"
                        ]["operations"]["claim"],
                        "auth_scope": "worker_api",
                    },
                    "complete": {
                        **_executor_manifest(plugin_id="scoped-registration")[
                            "remote_delegation"
                        ]["operations"]["complete"],
                        "auth_scope": "worker_api",
                    },
                },
                "callback_registration": {
                    "endpoint": "/webhooks",
                    "method": "POST",
                    "auth_scope": "public_api",
                    "lifecycle_events": ["progress", "completed"],
                    "payload_mapping": {
                        "url": {"source_path": "callback_url"},
                        "signing_secret": {"source_path": "callback_secret"},
                        "subscribed_events": {"source_path": "lifecycle_events"},
                    },
                },
            },
        )
        _enable_plugin(platform, manifest)
        platform.set_secret(
            "scoped-registration", "remote_auth", "public_api", "public-key-123"
        )
        platform.set_secret(
            "scoped-registration", "remote_auth", "worker_api", "worker-key-456"
        )

        result = asyncio.run(platform.re_register_callbacks("scoped-registration"))

        assert result["registered"] is True
        assert calls[0]["headers"]["X-API-Key"] == "public-key-123"
        assert "X-USR-Worker-Token" not in calls[0]["headers"]

    def test_callback_mapping_extracts_from_headers_and_body(
        self,
        tmp_path: Path,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import HTTPResponse, PluginPlatform

        async def http_request(
            method: str,
            url: str,
            payload: bytes | None,
            headers: dict[str, str],
            *,
            timeout: float = 30.0,
        ) -> HTTPResponse:
            return HTTPResponse(
                status_code=201,
                body=json.dumps(
                    {"result": {"id": "remote-1", "state": "queued"}}
                ).encode("utf-8"),
            )

        platform = PluginPlatform(tmp_path, http_request=http_request)
        manifest = _submitter_manifest(
            plugin_id="callback-submit",
            remote_delegation={
                **_submitter_manifest(plugin_id="callback-submit")["remote_delegation"],
                "integration_id": "callback-submit",
                "callbacks": {
                    "inbound": [
                        {
                            "handler_id": "on-complete",
                            "extract": {
                                "lifecycle_event": {
                                    "source_path": "callback.headers.x-event"
                                },
                                "correlation_id": {
                                    "source_path": "callback.body.correlation_id"
                                },
                                "external_job_id": {
                                    "source_path": "callback.body.job_id"
                                },
                                "result": {"source_path": "callback.body.result"},
                            },
                        }
                    ]
                },
            },
            callbacks=[{"handler_id": "on-complete", "auth_method": "hmac"}],
            capabilities=[
                "remote.jobs.submit",
                "remote.callbacks.receive",
                "webhooks.register",
            ],
        )
        _enable_plugin(platform, manifest)

        submission = platform.submit_delegated_job(
            "callback-submit",
            {"task": {"type": "scrape_and_download", "payload": {"username": "alice"}}},
        )
        result = asyncio.run(platform.execute_remote_submission(submission))

        callback_result = platform.receive_remote_callback(
            "callback-submit",
            "on-complete",
            {
                "correlation_id": result["correlation_id"],
                "job_id": "remote-1",
                "result": {"ok": True},
            },
            headers={"x-event": "completed"},
        )

        assert callback_result["accepted"] is True
        assert callback_result["correlated"] is True
        stored = platform.get_runtime_correlation(result["correlation_id"])
        assert stored is not None
        assert stored["status"] == "completed"

    @pytest.mark.parametrize("interrupted", [False, True])
    def test_executor_bridge_is_idempotent_for_duplicate_remote_work(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        interrupted: bool,
    ) -> None:
        from ultima_scraper_backend.plugin_system import platform as platform_module
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        calls: list[dict[str, Any]] = []

        class FakeJobManager:
            def __init__(self, redis: Any) -> None:
                self.redis = redis

            async def prepare_job(self, job: Any, **kwargs: Any) -> Any:
                return job

            async def activate_job(
                self,
                job: Any,
                *,
                distributed_mode: bool,
                priority: int = 0,
                ip_lock_key: str | None = None,
                backend_id: str | None = None,
                reserve_dedup: bool = True,
            ) -> tuple[str | None, list[Any]]:
                calls.append(
                    {
                        "job_id": job.job_id,
                        "job_name": job.name,
                        "distributed_mode": distributed_mode,
                        "backend_id": backend_id,
                    }
                )
                if interrupted:
                    raise RuntimeError("Runtime publication interrupted after preparation")
                return backend_id, []

        monkeypatch.setattr(platform_module, "JobManager", FakeJobManager)

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="bridge-plugin")
        _enable_plugin(platform, manifest)

        async def fake_dispatch_event(**_: Any) -> list[Any]:
            return []

        monkeypatch.setattr(platform, "dispatch_event", fake_dispatch_event)

        class FakeBackend:
            redis = object()
            distributed_mode = False
            instance_id = "backend-local"

        platform.attach_backend(FakeBackend())

        remote_message = {
            "job_type": "api_command",
            "id": "remote-job-1",
            "correlation_id": "corr-1",
            "payload": {"command": "sync", "args": {"force": True}},
        }

        first = asyncio.run(
            platform._bridge_remote_work_item("bridge-plugin", remote_message)
        )
        second = asyncio.run(
            platform._bridge_remote_work_item("bridge-plugin", remote_message)
        )

        assert first["local_job_id"] == second["local_job_id"]
        assert len(calls) == 1
        assert first["status"] == second["status"] == "claimed"

    def test_executor_bridge_imports_auth_bundle_before_job_activation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ultima_scraper_backend.plugin_system import platform as platform_module
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        captured_jobs: list[Any] = []
        imported_auth_calls: list[dict[str, Any]] = []

        class FakeBackendManager:
            async def _store_account(
                self,
                site: str,
                username: str | None,
                user_id: int | None,
                auth_export: dict[str, Any],
            ) -> Any:
                imported_auth_calls.append(
                    {
                        "site": site,
                        "username": username,
                        "user_id": user_id,
                        "auth_export": dict(auth_export),
                    }
                )

                class FakeAccount:
                    id = 4321

                return FakeAccount()

        class FakeJobManager:
            def __init__(self, redis: Any) -> None:
                self.redis = redis

            async def prepare_job(self, job: Any, **kwargs: Any) -> Any:
                return job

            async def activate_job(
                self,
                job: Any,
                *,
                distributed_mode: bool,
                priority: int = 0,
                ip_lock_key: str | None = None,
                backend_id: str | None = None,
                reserve_dedup: bool = True,
            ) -> tuple[str | None, list[Any]]:
                captured_jobs.append(job)
                return backend_id, []

        monkeypatch.setattr(
            "ultima_scraper_backend.api.dependencies.get_backend_manager",
            lambda: FakeBackendManager(),
        )
        monkeypatch.setattr(platform_module, "JobManager", FakeJobManager)

        platform = PluginPlatform(tmp_path)
        manifest = _workflow_executor_manifest()
        _enable_plugin(platform, manifest)

        async def fake_dispatch_event(**_: Any) -> list[Any]:
            return []

        monkeypatch.setattr(platform, "dispatch_event", fake_dispatch_event)

        class FakeBackend:
            redis = object()
            distributed_mode = False
            instance_id = "backend-local"

        platform.attach_backend(FakeBackend())

        remote_message = {
            "job_type": "scrape_download_workflow",
            "id": "remote-job-auth",
            "correlation_id": "corr-auth",
            "payload": {
                "site": "onlyfans",
                "username": "alice",
                "auth_bundle": {
                    "id": 321,
                    "username": "auth-owner",
                    "user_agent": "ua",
                    "cookie": "cookie-value",
                    "x_bc": "xbc-value",
                },
                "tasks": [
                    {
                        "kind": "scrape",
                        "alias": "scrape_posts",
                        "site_name": "OnlyFans",
                        "user_id": 123,
                        "user_username": "alice",
                        "content_type": "Posts",
                        "rescrape_existing": True,
                    },
                    {
                        "kind": "download",
                        "alias": "download_posts",
                        "depends_on_aliases": ["scrape_posts"],
                        "site_name": "OnlyFans",
                        "user_id": 123,
                        "user_username": "alice",
                        "content_type": "Posts",
                    },
                ],
            },
        }

        result = asyncio.run(
            platform._bridge_remote_work_item("workflow-executor", remote_message)
        )

        assert result["external_job_id"] == "remote-job-auth"
        assert imported_auth_calls[0]["site"] == "onlyfans"
        assert imported_auth_calls[0]["user_id"] == 321
        assert len(captured_jobs) == 1
        activated_job = captured_jobs[0]
        assert len(activated_job.tasks) == 2
        assert activated_job.tasks[0].auth_id == 4321
        assert activated_job.tasks[1].auth_id == 4321
        assert activated_job.tasks[1].depends_on == [activated_job.tasks[0].task_id]

        stored = platform.get_remote_submission("corr-auth")
        assert stored is not None
        assert stored["last_inbound_event"]["payload"]["auth_bundle"] == {
            "redacted": True
        }

    def test_executor_bridge_failures_mark_remote_job_failed_and_preserve_loop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        manifest = _workflow_executor_manifest()
        manifest["remote_delegation"]["operations"]["fail"] = {
            "transport": "http",
            "method": "POST",
            "endpoint": "/fail/{external_job_id}",
            "request_mapping": {
                "path_params": {
                    "external_job_id": {"source_path": "runtime.external_job_id"}
                },
                "body": {"failure_message": {"source_path": "payload.failure_message"}},
            },
            "response_mapping": {
                "external_job_id_path": "job.id",
                "remote_status_path": "job.status",
            },
        }
        _enable_plugin(platform, manifest)

        async def fake_dispatch_event(**_: Any) -> list[Any]:
            return []

        failed_actions: list[dict[str, Any]] = []

        async def fake_remote_action(
            plugin_id: str,
            action: str,
            remote_job_id: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            failed_actions.append(
                {
                    "plugin_id": plugin_id,
                    "action": action,
                    "remote_job_id": remote_job_id,
                    "payload": dict(payload),
                }
            )
            return {"success": True}

        monkeypatch.setattr(platform, "dispatch_event", fake_dispatch_event)
        monkeypatch.setattr(
            platform, "execute_remote_worker_action", fake_remote_action
        )

        class FakeBackend:
            redis = object()
            distributed_mode = False
            instance_id = "backend-local"

        platform.attach_backend(FakeBackend())

        remote_message = {
            "job_type": "scrape_and_download",
            "id": "remote-job-legacy",
            "correlation_id": "corr-legacy",
            "payload": {
                "site": "onlyfans",
                "username": "alice",
            },
        }

        result = asyncio.run(
            platform._bridge_remote_work_item("workflow-executor", remote_message)
        )

        assert result["external_job_id"] == "remote-job-legacy"
        assert result["status"] == "failed"
        assert result["local_status"] == "failed"
        assert "valid auth bundle" in (result["last_error"] or "")
        assert failed_actions == [
            {
                "plugin_id": "workflow-executor",
                "action": "fail",
                "remote_job_id": "remote-job-legacy",
                "payload": {
                    "failure_message": "Claimed remote work did not include a valid auth bundle"
                },
            }
        ]

        stored = platform.get_remote_submission("corr-legacy")
        assert stored is not None
        assert stored["status"] == "failed"
        assert stored["remote_status"] == "failed"
        assert stored["last_inbound_event"]["event"] == "bridge_failed"

    def test_local_job_events_mirror_back_to_remote_actions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ultima_scraper_backend.plugin_system import platform as platform_module
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        class FakeJobManager:
            def __init__(self, redis: Any) -> None:
                self.redis = redis

            async def prepare_job(self, job: Any, **kwargs: Any) -> Any:
                return job

            async def activate_job(
                self,
                job: Any,
                *,
                distributed_mode: bool,
                priority: int = 0,
                ip_lock_key: str | None = None,
                backend_id: str | None = None,
                reserve_dedup: bool = True,
            ) -> tuple[str | None, list[Any]]:
                return backend_id, []

        mirrored: list[dict[str, Any]] = []

        async def fake_remote_action(
            plugin_id: str,
            action: str,
            remote_job_id: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            mirrored.append(
                {
                    "plugin_id": plugin_id,
                    "action": action,
                    "remote_job_id": remote_job_id,
                    "payload": payload,
                }
            )
            return {"success": True}

        monkeypatch.setattr(platform_module, "JobManager", FakeJobManager)

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="mirror-plugin")
        _enable_plugin(platform, manifest)

        async def fake_dispatch_event(**_: Any) -> list[Any]:
            return []

        monkeypatch.setattr(platform, "dispatch_event", fake_dispatch_event)
        monkeypatch.setattr(
            platform, "execute_remote_worker_action", fake_remote_action
        )

        class FakeBackend:
            redis = object()
            distributed_mode = False
            instance_id = "backend-local"

        platform.attach_backend(FakeBackend())

        remote_message = {
            "job_type": "api_command",
            "id": "remote-job-2",
            "correlation_id": "corr-2",
            "payload": {"command": "sync", "args": {"force": True}},
        }
        correlation = asyncio.run(
            platform._bridge_remote_work_item("mirror-plugin", remote_message)
        )

        asyncio.run(
            platform._process_local_job_event(
                {"event": "job_completed", "job_id": correlation["local_job_id"]}
            )
        )

        assert mirrored
        assert mirrored[0]["action"] == "complete"
        assert mirrored[0]["remote_job_id"] == "remote-job-2"


class TestRemoteAdapterRobustness:
    """Integration tests for remote delegation robustness (GAPs 1-5)."""

    def test_mirror_logs_error_and_records_last_error_on_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GAP 1: Mirror exceptions are logged and recorded on the submission record."""
        from ultima_scraper_backend.plugin_system import platform as platform_module
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        class FakeJobManager:
            def __init__(self, redis: Any) -> None:
                self.redis = redis

            async def prepare_job(self, job: Any, **kwargs: Any) -> Any:
                return job

            async def activate_job(
                self,
                job: Any,
                *,
                distributed_mode: bool,
                priority: int = 0,
                ip_lock_key: str | None = None,
                backend_id: str | None = None,
                reserve_dedup: bool = True,
            ) -> tuple[str | None, list[Any]]:
                return backend_id, []

        async def fake_remote_action_fail(
            plugin_id: str,
            action: str,
            remote_job_id: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            raise ConnectionError("Remote unreachable")

        monkeypatch.setattr(platform_module, "JobManager", FakeJobManager)
        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="mirror-err")
        _enable_plugin(platform, manifest)

        async def fake_dispatch_event(**_: Any) -> list[Any]:
            return []

        monkeypatch.setattr(platform, "dispatch_event", fake_dispatch_event)
        monkeypatch.setattr(
            platform, "execute_remote_worker_action", fake_remote_action_fail
        )

        class FakeBackend:
            redis = object()
            distributed_mode = False
            instance_id = "backend-local"

        platform.attach_backend(FakeBackend())

        remote_message = {
            "job_type": "api_command",
            "id": "remote-err-1",
            "correlation_id": "corr-err",
            "payload": {"command": "test"},
        }
        correlation = asyncio.run(
            platform._bridge_remote_work_item("mirror-err", remote_message)
        )

        # Process a completed event — mirror should fail but NOT raise
        asyncio.run(
            platform._process_local_job_event(
                {"event": "job_completed", "job_id": correlation["local_job_id"]}
            )
        )

        stored = platform.get_remote_submission("corr-err")
        assert stored is not None
        assert stored["last_error"] is not None
        assert "mirror" in stored["last_error"]

    def test_mirror_records_remote_action_failure_result(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GAP 1: When remote action returns success=False, record the error."""
        from ultima_scraper_backend.plugin_system import platform as platform_module
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        class FakeJobManager:
            def __init__(self, redis: Any) -> None:
                self.redis = redis

            async def prepare_job(self, job: Any, **kwargs: Any) -> Any:
                return job

            async def activate_job(
                self,
                job: Any,
                *,
                distributed_mode: bool,
                priority: int = 0,
                ip_lock_key: str | None = None,
                backend_id: str | None = None,
                reserve_dedup: bool = True,
            ) -> tuple[str | None, list[Any]]:
                return backend_id, []

        async def fake_remote_action_soft_fail(
            plugin_id: str,
            action: str,
            remote_job_id: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            return {"success": False, "error": "Remote rejected action"}

        monkeypatch.setattr(platform_module, "JobManager", FakeJobManager)
        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="mirror-soft")
        _enable_plugin(platform, manifest)

        async def fake_dispatch_event(**_: Any) -> list[Any]:
            return []

        monkeypatch.setattr(platform, "dispatch_event", fake_dispatch_event)
        monkeypatch.setattr(
            platform, "execute_remote_worker_action", fake_remote_action_soft_fail
        )

        class FakeBackend:
            redis = object()
            distributed_mode = False
            instance_id = "backend-local"

        platform.attach_backend(FakeBackend())

        remote_message = {
            "job_type": "api_command",
            "id": "remote-soft-1",
            "correlation_id": "corr-soft",
            "payload": {"command": "test"},
        }
        correlation = asyncio.run(
            platform._bridge_remote_work_item("mirror-soft", remote_message)
        )

        asyncio.run(
            platform._process_local_job_event(
                {"event": "job_completed", "job_id": correlation["local_job_id"]}
            )
        )

        stored = platform.get_remote_submission("corr-soft")
        assert stored is not None
        assert stored["last_error"] is not None
        assert "Remote rejected action" in stored["last_error"]

    def test_stale_submission_detected_and_marked_failed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GAP 2: Submissions stuck past the threshold are detected and marked failed."""
        from datetime import UTC, datetime, timedelta

        from ultima_scraper_backend.plugin_system import platform as platform_module
        from ultima_scraper_backend.plugin_system.platform import (
            PluginPlatform,
            RemoteSubmissionRecord,
        )

        class FakeJobManager:
            def __init__(self, redis: Any) -> None:
                self.redis = redis

            async def prepare_job(self, job: Any, **kwargs: Any) -> Any:
                return job

            async def activate_job(
                self,
                job: Any,
                *,
                distributed_mode: bool,
                priority: int = 0,
                ip_lock_key: str | None = None,
                backend_id: str | None = None,
                reserve_dedup: bool = True,
            ) -> tuple[str | None, list[Any]]:
                return backend_id, []

        failed_reports: list[dict[str, Any]] = []

        async def fake_remote_action(
            plugin_id: str,
            action: str,
            remote_job_id: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            failed_reports.append(
                {"action": action, "remote_job_id": remote_job_id, "payload": payload}
            )
            return {"success": True}

        monkeypatch.setattr(platform_module, "JobManager", FakeJobManager)
        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="stale-test")
        _enable_plugin(platform, manifest)

        monkeypatch.setattr(
            platform, "execute_remote_worker_action", fake_remote_action
        )

        # Manually inject a stale submission
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        rec = RemoteSubmissionRecord(
            correlation_id="corr-stale",
            plugin_id="stale-test",
            integration_id="remote-exec",
            payload_hash="abc",
        )
        rec.external_job_id = "ext-stale-1"
        rec.status = "in_progress"
        rec.updated_at = old_time
        platform._submissions["corr-stale"] = rec
        platform._external_id_index["ext-stale-1"] = "corr-stale"

        stale_ids = asyncio.run(
            platform._detect_stale_submissions("stale-test", stale_threshold_seconds=60)
        )

        assert stale_ids == ["corr-stale"]
        stored = platform.get_remote_submission("corr-stale")
        assert stored is not None
        assert stored["status"] == "failed"
        assert "Stale submission" in (stored["last_error"] or "")
        # Check that failure was reported to remote
        assert len(failed_reports) == 1
        assert failed_reports[0]["action"] == "fail"
        assert failed_reports[0]["remote_job_id"] == "ext-stale-1"

    def test_stale_detection_skips_terminal_and_fresh_submissions(
        self,
        tmp_path: Path,
    ) -> None:
        """GAP 2: Terminal and recently-updated submissions are not marked stale."""
        from datetime import UTC, datetime, timedelta

        from ultima_scraper_backend.plugin_system.platform import (
            PluginPlatform,
            RemoteSubmissionRecord,
        )

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="skip-test")
        _enable_plugin(platform, manifest)

        # Completed submission (terminal — should skip)
        rec1 = RemoteSubmissionRecord(
            correlation_id="corr-done",
            plugin_id="skip-test",
            integration_id="remote-exec",
            payload_hash="a",
        )
        rec1.status = "completed"
        rec1.updated_at = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        platform._submissions["corr-done"] = rec1

        # Fresh in-progress submission (should skip)
        rec2 = RemoteSubmissionRecord(
            correlation_id="corr-fresh",
            plugin_id="skip-test",
            integration_id="remote-exec",
            payload_hash="b",
        )
        rec2.status = "in_progress"
        rec2.updated_at = datetime.now(UTC).isoformat()
        platform._submissions["corr-fresh"] = rec2

        stale_ids = asyncio.run(
            platform._detect_stale_submissions("skip-test", stale_threshold_seconds=60)
        )

        assert stale_ids == []
        assert platform._submissions["corr-done"].status == "completed"
        assert platform._submissions["corr-fresh"].status == "in_progress"

    def test_remote_delegation_overview_aggregates_submission_data(
        self,
        tmp_path: Path,
    ) -> None:
        """GAP 3: Overview endpoint returns correct aggregate submission data."""
        from ultima_scraper_backend.plugin_system.platform import (
            PluginPlatform,
            RemoteSubmissionRecord,
        )

        platform = PluginPlatform(tmp_path)

        for i, (status, error) in enumerate(
            [
                ("in_progress", None),
                ("completed", None),
                ("failed", "test error"),
                ("pending", None),
            ]
        ):
            rec = RemoteSubmissionRecord(
                correlation_id=f"corr-{i}",
                plugin_id="overview-plugin",
                integration_id="remote-exec",
                payload_hash=str(i),
            )
            rec.status = status
            rec.last_error = error
            platform._submissions[f"corr-{i}"] = rec

        overview = platform.get_remote_delegation_overview()

        assert overview["submissions"]["total"] == 4
        assert overview["submissions"]["active"] == 2  # in_progress + pending
        assert overview["submissions"]["terminal"] == 2  # completed + failed
        assert overview["submissions"]["errored"] == 1
        assert "overview-plugin" in overview["per_plugin"]
        pp = overview["per_plugin"]["overview-plugin"]
        assert pp["active"] == 2
        assert pp["completed"] == 1
        assert pp["failed"] == 1

    def test_reconcile_loop_recovers_after_transient_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A transient reconcile failure must not permanently stop its supervisor."""
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        registration_attempts = 0
        reconcile_attempts = 0

        async def fake_registration(plugin_id: str) -> None:
            nonlocal registration_attempts
            registration_attempts += 1
            if registration_attempts == 1:
                raise ConnectionError("Remote down")

        async def fake_reconcile(plugin_id: str) -> None:
            nonlocal reconcile_attempts
            reconcile_attempts += 1

        platform = PluginPlatform(tmp_path)
        monkeypatch.setattr(
            platform,
            "_plugin_runtime_enabled",
            lambda plugin_id: registration_attempts < 2,
        )
        monkeypatch.setattr(
            platform,
            "_ensure_callback_registration",
            fake_registration,
        )
        monkeypatch.setattr(
            platform,
            "_reconcile_plugin_submissions",
            fake_reconcile,
        )

        sleep_durations: list[float] = []

        async def fast_sleep(seconds: float) -> None:
            sleep_durations.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        asyncio.run(platform._run_plugin_reconcile_loop("recovery-test"))

        assert registration_attempts == 2
        assert reconcile_attempts == 1
        assert sleep_durations == [5, 30]
        warning_records = [
            record
            for record in caplog.records
            if "reconcile loop" in record.getMessage()
            and "unavailable" in record.getMessage()
        ]
        assert len(warning_records) == 1
        assert warning_records[0].exc_info is None

    def test_claim_loop_retries_on_initial_connectivity_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """GAP 5: Claim loop retries with backoff when remote is initially unreachable."""
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        claim_attempts: list[str] = []
        fail_count = 2  # First 2 attempts fail

        async def fake_claim(plugin_id: str) -> bool:
            claim_attempts.append(plugin_id)
            if len(claim_attempts) <= fail_count:
                raise ConnectionError("Remote down")
            return False

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="retry-test")
        _enable_plugin(platform, manifest)

        # Track runtime enabled calls to eventually stop the loop
        enabled_count = 0

        def limited_enabled(pid: str) -> bool:
            nonlocal enabled_count
            enabled_count += 1
            # Let the loop recover, then stop after a few successful polls.
            if enabled_count > 6:
                return False
            return True

        monkeypatch.setattr(platform, "_plugin_runtime_enabled", limited_enabled)
        monkeypatch.setattr(platform, "_claim_remote_work", fake_claim)

        # Replace asyncio.sleep to avoid real delays
        sleep_durations: list[float] = []

        async def fast_sleep(seconds: float) -> None:
            sleep_durations.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        asyncio.run(platform._run_plugin_claim_loop("retry-test"))

        # Should have retried after failures
        assert len(claim_attempts) >= 3
        # First two should have failed, third should succeed
        assert sleep_durations[0] == 5  # Initial backoff
        assert sleep_durations[1] == 10  # Doubled backoff
        warning_records = [
            record
            for record in caplog.records
            if "remote unavailable" in record.getMessage()
        ]
        assert len(warning_records) == 1
        assert warning_records[0].exc_info is None

    def test_claim_loop_recovers_when_remote_fails_after_initial_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient outage must not permanently stop an established claim loop."""
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        claim_attempts = 0

        async def fake_claim(plugin_id: str) -> bool:
            nonlocal claim_attempts
            claim_attempts += 1
            if claim_attempts == 2:
                raise ConnectionError("Remote restarted")
            return False

        platform = PluginPlatform(tmp_path)
        manifest = _executor_manifest(plugin_id="recovery-test")
        _enable_plugin(platform, manifest)

        monkeypatch.setattr(
            platform,
            "_plugin_runtime_enabled",
            lambda plugin_id: claim_attempts < 3,
        )
        monkeypatch.setattr(platform, "_claim_remote_work", fake_claim)

        sleep_durations: list[float] = []

        async def fast_sleep(seconds: float) -> None:
            sleep_durations.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        asyncio.run(platform._run_plugin_claim_loop("recovery-test"))

        assert claim_attempts == 3
        assert sleep_durations == [5, 5, 5]
