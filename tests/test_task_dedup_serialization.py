import json

import pytest
from ultima_scraper_api import ContentType
from ultima_scraper_backend.job_system import Task, TaskType, build_task


@pytest.mark.parametrize("task_type", [TaskType.SCRAPE, TaskType.DOWNLOAD])
@pytest.mark.parametrize("content_type", list(ContentType))
def test_reservation_key_matches_worker_key_after_json_roundtrip(
    task_type, content_type
):
    task = build_task(
        task_type,
        site_name="OnlyFans",
        user_id=7,
        user_username="fixture",
        content_type=content_type,
    )
    restored = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert task.dedup_key == restored.dedup_key
    assert f":{content_type.value}:" in task.dedup_key
