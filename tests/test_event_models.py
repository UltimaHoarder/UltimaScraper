"""Test typed event models for validation and serialization."""

import json
import time
from datetime import datetime

import pytest
from pydantic import ValidationError

from ultima_scraper_backend.job_system.events import (
    APICommandEvent,
    JobProgressEvent,
    OperationProgressEvent,
    TaskProgressEvent,
    TaskStatusEvent,
)
from ultima_scraper_api.job_events import create_download_progress_event


class TestEventModels:
    """Test Pydantic event models for type safety and serialization."""

    def test_download_progress_event_valid(self):
        """Test valid OperationProgressEvent (download) creation and serialization."""
        event = OperationProgressEvent(
            event="download_progress",
            job_id="job_123",
            task_id="task_456",
            download_id="download_789",
            username="testuser",
            user_id=12345,
            content_type="Posts",
            media_type="images",
            status="progress",
            media_id="media_001",
            path="/path/to/file.jpg",
            bytes=1024,
            total_bytes=10240,
            speed_bps=1024.5,
            avg_speed_bps=900.3,
            completed=5,
            failed=1,
            total=10,
        )

        assert event.event == "download_progress"
        assert event.is_download
        assert not event.is_scrape
        assert event.is_in_progress
        assert event.job_id == "job_123"
        assert event.task_id == "task_456"
        assert event.username == "testuser"
        assert event.status == "progress"
        assert isinstance(event.timestamp, datetime)

        # Test JSON serialization
        data = event.model_dump(mode="json")
        assert data["event"] == "download_progress"
        assert data["user_id"] == 12345
        assert isinstance(data["timestamp"], str)  # ISO format

        # Can round-trip through JSON
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["event"] == "download_progress"

    def test_download_progress_event_invalid_status(self):
        """Test OperationProgressEvent (download) rejects invalid status."""
        with pytest.raises(ValidationError) as exc_info:
            OperationProgressEvent(
                event="download_progress",
                job_id="job_123",
                download_id="download_789",
                username="testuser",
                user_id=12345,
                content_type="Posts",
                media_type="images",
                status="invalid_status",  # Not in Literal
                total=10,
            )

        assert "status" in str(exc_info.value)

    def test_download_progress_event_negative_bytes(self):
        """Test OperationProgressEvent (download) rejects negative bytes."""
        with pytest.raises(ValidationError) as exc_info:
            OperationProgressEvent(
                event="download_progress",
                job_id="job_123",
                download_id="download_789",
                username="testuser",
                user_id=12345,
                content_type="Posts",
                media_type="images",
                status="progress",
                bytes=-100,  # Invalid negative
                total=10,
            )

        assert "bytes" in str(exc_info.value)

    def test_download_progress_factory_tracks_streaming_and_expected_bytes(self):
        """Streaming deltas accumulate before a whole file completes."""
        progress_start = time.perf_counter() - 2.0
        progress_state = {
            "completed": 0,
            "failed": 0,
            "total_bytes": 0,
            "processed_bytes": 0,
            "expected_bytes": 0,
            "speed_bps": 0.0,
            "last_time": progress_start,
        }

        progress = create_download_progress_event(
            job_id="job_123",
            task_id="task_456",
            download_id="download_789",
            username="testuser",
            user_id=12345,
            content_type="Posts",
            worker_id="worker-1",
            dm_event={
                "status": "progress",
                "bytes": 2048,
                "processed_bytes": 3072,
                "expected_bytes": 8192,
                "completed": 0,
                "failed": 0,
            },
            progress_state=progress_state,
            progress_start=progress_start,
            total_downloads=2,
        )

        assert progress.status == "progress"
        assert progress.bytes == 2048
        assert progress.total_bytes == 2048
        assert progress.processed_bytes == 3072
        assert progress.expected_bytes == 8192
        assert progress.speed_bps > 0
        assert progress.avg_speed_bps > 0

        completed = create_download_progress_event(
            job_id="job_123",
            task_id="task_456",
            download_id="download_789",
            username="testuser",
            user_id=12345,
            content_type="Posts",
            worker_id="worker-1",
            dm_event={
                "status": "completed",
                "bytes": 0,
                "processed_bytes": 4096,
                "expected_bytes": 8192,
                "completed": 1,
                "failed": 0,
            },
            progress_state=progress_state,
            progress_start=progress_start,
            total_downloads=2,
        )

        assert completed.total_bytes == 2048
        assert completed.processed_bytes == 4096
        assert completed.expected_bytes == 8192
        assert completed.speed_bps == progress.speed_bps

    def test_api_command_event_valid(self):
        """Test APICommandEvent creation."""
        event = APICommandEvent(
            job_id="job_123",
            task_id="task_456",
            command="get_user",
            success=True,
            message="User retrieved successfully",
            output={"username": "testuser", "id": 12345},
            execution_time=1.23,
        )

        assert event.event == "api_command_result"
        assert event.command == "get_user"
        assert event.success is True
        assert event.output["username"] == "testuser"

    def test_api_command_event_negative_execution_time(self):
        """Test APICommandEvent rejects negative execution time."""
        with pytest.raises(ValidationError) as exc_info:
            APICommandEvent(
                job_id="job_123",
                command="get_user",
                success=True,
                execution_time=-1.0,  # Invalid negative
            )

        assert "execution_time" in str(exc_info.value)

    def test_scrape_progress_event_valid(self):
        """Test OperationProgressEvent (scrape) creation."""
        event = OperationProgressEvent(
            event="scrape_progress",
            job_id="job_123",
            task_id="task_456",
            username="testuser",
            user_id=12345,
            content_type="Posts",
            status="progress",
            items_scraped=50,
            items_saved=48,
            total_items=100,
            page=2,
            has_more=True,
        )

        assert event.event == "scrape_progress"
        assert event.is_scrape
        assert not event.is_download
        assert event.is_in_progress
        assert event.items_scraped == 50
        assert event.items_saved == 48
        assert event.page == 2

    def test_job_progress_event_valid(self):
        """Test JobProgressEvent creation."""
        event = JobProgressEvent(
            job_id="job_123",
            job_name="Download User Posts",
            status="running",
            total_tasks=10,
            completed_tasks=5,
            failed_tasks=1,
        )

        assert event.event == "job_progress"
        assert event.job_name == "Download User Posts"
        assert event.completed_tasks == 5

    def test_task_started_event(self):
        """Test TaskStatusEvent with task_started."""
        event = TaskStatusEvent(
            event="task_started",
            job_id="job_123",
            task_id="task_456",
            task_type="DOWNLOAD",
            worker_id="worker_1",
        )

        assert event.event == "task_started"
        assert event.is_started
        assert not event.is_completed
        assert not event.is_failed
        assert event.task_type == "DOWNLOAD"
        assert event.worker_id == "worker_1"

    def test_task_completed_event(self):
        """Test TaskStatusEvent with task_completed."""
        event = TaskStatusEvent(
            event="task_completed",
            job_id="job_123",
            task_id="task_456",
            task_type="SCRAPE",
            execution_time=45.6,
            message="Scraped 100 posts",
        )

        assert event.event == "task_completed"
        assert event.is_completed
        assert not event.is_started
        assert not event.is_failed
        assert event.execution_time == 45.6

    def test_task_failed_event(self):
        """Test TaskStatusEvent with task_failed."""
        event = TaskStatusEvent(
            event="task_failed",
            job_id="job_123",
            task_id="task_456",
            task_type="DOWNLOAD",
            error="Network timeout",
            traceback="Traceback (most recent call last)...",
        )

        assert event.event == "task_failed"
        assert event.is_failed
        assert not event.is_started
        assert not event.is_completed
        assert event.error == "Network timeout"
        assert event.traceback is not None

    def test_event_immutability(self):
        """Test that events are immutable (frozen)."""
        event = TaskProgressEvent(
            job_id="job_123",
            task_id="task_456",
            progress=50.0,
            message="Halfway done",
        )

        # Attempt to modify should raise error
        with pytest.raises(ValidationError):
            event.progress = 75.0  # type: ignore[misc]

    def test_all_events_have_timestamp(self):
        """Test that all events automatically include timestamps."""
        events = [
            TaskProgressEvent(job_id="j1", task_id="t1", progress=50.0),
            OperationProgressEvent(
                event="download_progress",
                job_id="j1",
                download_id="d1",
                username="u1",
                user_id=1,
                content_type="Posts",
                media_type="images",
                status="progress",
                total=10,
            ),
            JobProgressEvent(
                job_id="j1",
                job_name="Test",
                status="running",
                total_tasks=5,
                completed_tasks=2,
                failed_tasks=0,
            ),
        ]

        for event in events:
            assert hasattr(event, "timestamp")
            assert isinstance(event.timestamp, datetime)
