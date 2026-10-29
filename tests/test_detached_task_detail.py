import json
import pytest
from sqlalchemy.orm.exc import DetachedInstanceError

from ultima_scraper_backend.api.routes.jobs import (
    _central_task_row_to_detail,
)
from ultima_scraper_backend.api.routes.mps_history import record_detail
from ultima_scraper_backend.database.job_history import TaskRecord


class FakeDetachedCentralTaskModel:
    """Simulates a SQLAlchemy model row whose deferred columns raise DetachedInstanceError."""

    def __init__(
        self,
        task_id: str = "task-123",
        job_id: str = "job-abc",
        task_type: str = "scrape",
        content_type: str = "Posts",
        status: str = "completed",
        items_total: int = 10,
        items_processed: int = 10,
        site: str = "OnlyFans",
        username: str = "creator",
        started_at=None,
        completed_at=None,
        error=None,
        result_json: str | None = None,
        message: str | None = "Completed scrape",
        worker_id: str | None = "worker-1",
    ):
        self.task_id = task_id
        self.job_id = job_id
        self.task_type = task_type
        self.content_type = content_type
        self.status = status
        self.items_total = items_total
        self.items_processed = items_processed
        self.site = site
        self.username = username
        self.started_at = started_at
        self.completed_at = completed_at
        self.error = error
        self.message = message
        self.worker_id = worker_id
        self._result_json = result_json

    @property
    def result_json(self):
        if self._result_json is None:
            raise DetachedInstanceError(
                "Parent instance is not bound to a Session; deferred load operation of attribute 'result_json' cannot proceed"
            )
        return self._result_json

    @property
    def definition_json(self):
        raise DetachedInstanceError(
            "Parent instance is not bound to a Session; deferred load operation of attribute 'definition_json' cannot proceed"
        )


def test_central_task_row_to_detail_handles_detached_row_without_error():
    row = FakeDetachedCentralTaskModel(
        task_id="task-detached-1",
        message="Finished successfully",
        worker_id="worker-w1",
    )
    # Accessing row.definition_json directly raises DetachedInstanceError
    with pytest.raises(DetachedInstanceError):
        _ = row.definition_json

    # But _central_task_row_to_detail must not raise DetachedInstanceError
    detail = _central_task_row_to_detail(row)
    assert detail.task_id == "task-detached-1"
    assert detail.status == "completed"
    assert detail.worker_id == "worker-w1"
    assert detail.result == {"message": "Finished successfully"}


def test_central_task_row_to_detail_extracts_proxy_telemetry_from_output_and_metrics():
    result_data = {
        "output": {
            "resolved_route_url": "http://user:pass@proxy1.example.com:8080",
            "proxy_routes": [
                "http://user:pass@proxy1.example.com:8080",
                "http://user:pass@proxy2.example.com:8080",
                None,
            ],
            "resolved_route_index": 0,
        },
        "metrics": {
            "proxy_url": "http://user:pass@proxy1.example.com:8080",
            "proxy_hop_used": 0,
            "proxy_routes": [
                "http://user:pass@proxy1.example.com:8080",
                "http://user:pass@proxy2.example.com:8080",
                None,
            ],
        },
    }
    row = FakeDetachedCentralTaskModel(
        task_id="task-proxy-1",
        result_json=json.dumps(result_data),
    )
    detail = _central_task_row_to_detail(row)
    assert detail.proxy_url == "http://user:pass@proxy1.example.com:8080"
    assert detail.proxy_routes == [
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
        None,
    ]
    assert detail.proxy_hop_used == 0


def test_record_detail_integrates_definition_and_archive_without_detached_error():
    definition_obj = {
        "id": "task-rec-1",
        "job_id": "job-test",
        "task_type": "scrape",
        "title": "Scrape task",
        "payload": {
            "guest_proxy_url": "http://user:pass@primary.com:8000",
            "guest_fallback_proxy_urls": ["http://user:pass@fallback1.com:8000"],
            "guest_direct_route_index": 2,
        },
    }
    definition_str = json.dumps(definition_obj)

    row = FakeDetachedCentralTaskModel(
        task_id="task-rec-1",
        job_id="job-test",
        result_json=json.dumps(
            {
                "output": {
                    "resolved_route_url": "http://user:pass@fallback1.com:8000",
                    "resolved_route_index": 1,
                    "proxy_routes": [
                        "http://user:pass@primary.com:8000",
                        "http://user:pass@fallback1.com:8000",
                        None,
                    ],
                }
            }
        ),
    )

    record = TaskRecord(
        task_id="task-rec-1",
        read_bytes=100,
        archive=row,
        definition=definition_str,
    )

    detail = record_detail(record)
    assert detail is not None
    assert detail.task_id == "task-rec-1"
    assert detail.proxy_url == "http://user:pass@fallback1.com:8000"
    assert detail.proxy_routes == [
        "http://user:pass@primary.com:8000",
        "http://user:pass@fallback1.com:8000",
        None,
    ]
    assert detail.proxy_hop_used == 1


def test_record_detail_resolves_direct_route_hop():
    definition_obj = {
        "id": "task-direct-1",
        "job_id": "job-test",
        "task_type": "scrape",
        "payload": {
            "guest_proxy_url": "http://user:pass@primary.com:8000",
            "guest_fallback_proxy_urls": ["http://user:pass@fallback1.com:8000"],
            "guest_direct_route_index": 2,
        },
    }
    definition_str = json.dumps(definition_obj)

    row = FakeDetachedCentralTaskModel(
        task_id="task-direct-1",
        job_id="job-test",
        result_json=json.dumps(
            {
                "output": {
                    "resolved_route_url": None,
                    "resolved_route_index": 2,
                    "proxy_routes": [
                        "http://user:pass@primary.com:8000",
                        "http://user:pass@fallback1.com:8000",
                        None,
                    ],
                }
            }
        ),
    )

    record = TaskRecord(
        task_id="task-direct-1",
        read_bytes=100,
        archive=row,
        definition=definition_str,
    )

    detail = record_detail(record)
    assert detail is not None
    assert detail.task_id == "task-direct-1"
    assert detail.proxy_url is None
    assert detail.proxy_routes == [
        "http://user:pass@primary.com:8000",
        "http://user:pass@fallback1.com:8000",
        None,
    ]
    assert detail.proxy_hop_used == 2

