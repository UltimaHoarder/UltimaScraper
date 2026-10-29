from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.helpers import thumbnails as thumbnail_module


def test_remote_thumbnail_is_published_atomically_and_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    generated_paths: list[Path] = []
    generated_commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        generated_commands.append(command)
        generated_path = Path(command[-1])
        generated_paths.append(generated_path)
        generated_path.write_bytes(b"complete-png")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(thumbnail_module.subprocess, "run", fake_run)

    first = thumbnail_module.get_or_create_remote_thumbnail(
        "https://cdn.example.test/video.mp4",
        "onlyfans:123",
        tmp_path,
        is_video=True,
        custom_cookies="CloudFront-Policy=policy",
        user_agent="Stored Agent",
        authorization="Bearer stored",
        proxy_url="http://proxy.example.test:8080",
    )
    second = thumbnail_module.get_or_create_remote_thumbnail(
        "https://cdn.example.test/video.mp4",
        "onlyfans:123",
        tmp_path,
        is_video=True,
        custom_cookies="CloudFront-Policy=policy",
        user_agent="Stored Agent",
        authorization="Bearer stored",
        proxy_url="http://proxy.example.test:8080",
    )

    assert first is not None
    assert first == second
    assert first.read_bytes() == b"complete-png"
    assert generated_paths != [first]
    assert len(generated_paths) == 1
    assert not generated_paths[0].exists()
    assert "-http_proxy" in generated_commands[0]
    assert "http://proxy.example.test:8080" in generated_commands[0]
    assert "-user_agent" in generated_commands[0]
    headers = generated_commands[0][generated_commands[0].index("-headers") + 1]
    assert "Cookie: CloudFront-Policy=policy\r\n" in headers
    assert "Authorization: Bearer stored\r\n" in headers


def test_failed_overwrite_preserves_existing_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    output = thumbnail_module.get_thumbnail_path(source, tmp_path / "thumbnails")
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing-png")

    monkeypatch.setattr(
        thumbnail_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="failed"),
    )

    result = thumbnail_module.generate_thumbnail(
        source,
        tmp_path / "thumbnails",
        is_video=True,
        overwrite=True,
    )

    assert result is None
    assert output.read_bytes() == b"existing-png"
