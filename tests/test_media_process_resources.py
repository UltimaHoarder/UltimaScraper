"""Native local subprocess, cancellation, queue and file-ownership checks."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import threading
import time

import pytest

from ultima_scraper_api.apis.onlyfans.classes.only_drm import MediaFormatter, OnlyDRM
from ultima_scraper_api.helpers.processes import ProcessResult, run_process, run_process_sync


@pytest.fixture(autouse=True)
def independent_environment(monkeypatch):
    for name in (
        "ULTIMA_MEDIA_PROCESS_CONCURRENCY",
        "ULTIMA_MEDIA_PROCESS_QUEUE_ENTRIES",
        "ULTIMA_MEDIA_PROCESS_OUTPUT_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_large_dual_pipe_output_is_bounded_and_does_not_block_the_loop():
    ticks = 0
    running = True

    async def tick():
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.001)

    ticker = asyncio.create_task(tick())
    try:
        result = await run_process(
            [
                sys.executable,
                "-c",
                "import os,time; time.sleep(.08); "
                "[(os.write(1,b'a'*8192),os.write(2,b'b'*8192)) for _ in range(1024)]; "
                "os.write(1,b'OUTEND');os.write(2,b'ERREND')",
            ],
            output_bytes=257,
        )
    finally:
        running = False
        await ticker
    assert ticks > 10
    assert result.returncode == 0
    assert len(result.stdout) == len(result.stderr) == 257
    assert result.stdout.endswith(b"OUTEND") and result.stderr.endswith(b"ERREND")
    assert result.stdout_truncated and result.stderr_truncated


def test_synchronous_compatibility_has_the_same_output_bound():
    result = run_process_sync(
        [
            sys.executable,
            "-c",
            "import os;[(os.write(1,b'a'*8192),os.write(2,b'b'*8192)) for _ in range(128)]",
        ],
        output_bytes=31,
    )
    assert result.returncode == 0
    assert result.stdout == b"a" * 31 and result.stderr == b"b" * 31
    assert result.stdout_truncated and result.stderr_truncated


@pytest.mark.asyncio
async def test_cancellation_during_spawn_reaps_before_return(monkeypatch):
    import ultima_scraper_api.helpers.processes as process_module

    started, release = asyncio.Event(), asyncio.Event()
    real_spawn = asyncio.create_subprocess_exec
    spawned = []

    async def delayed_spawn(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        spawned.append(process)
        started.set()
        await release.wait()
        return process

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", delayed_spawn)
    caller = asyncio.create_task(
        run_process([sys.executable, "-c", "import time;time.sleep(30)"])
    )
    await asyncio.wait_for(started.wait(), 2)
    caller.cancel()
    await asyncio.sleep(0)
    assert not caller.done()
    caller.cancel()  # Repeated cancellation still retains startup ownership.
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(caller, 2)
    assert spawned[0].returncode is not None
    if os.name == "posix":
        with pytest.raises(ChildProcessError):
            os.waitpid(spawned[0].pid, os.WNOHANG)


@pytest.mark.asyncio
async def test_stdout_consumer_error_kills_and_reaps_a_noisy_process():
    def broken(_):
        raise ValueError("fixture parser failed")

    with pytest.raises(ValueError, match="fixture parser failed"):
        await asyncio.wait_for(
            run_process(
                [
                    sys.executable,
                    "-c",
                    "import os;\nwhile True: os.write(1,b'x'*8192)",
                ],
                stdout_consumer=broken,
                output_bytes=19,
            ),
            2,
        )


@pytest.fixture
def media_tools(tmp_path, monkeypatch):
    binary_dir = tmp_path / "tools"
    binary_dir.mkdir()
    program = (
        "#!"
        + sys.executable
        + "\n"
        + """
import os, pathlib, sys, time
name = pathlib.Path(sys.argv[0]).name
if name == "mp4dump":
    if pathlib.Path(sys.argv[1]).read_bytes().startswith(b"PLAIN"):
        print("avc1")
    else:
        os.write(1,b"en"); time.sleep(.01); os.write(1,b"cv\\n")
        for _ in range(128): os.write(1,b"x"*8192)
elif name == "ffprobe":
    print("mov,mp4,m4a,3gp,3g2,mj2")
else:
    if name == "mp4decrypt":
        source, output = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    else:
        source = pathlib.Path(sys.argv[sys.argv.index("-i")+1])
        output = next(pathlib.Path(arg) for arg in sys.argv if arg.endswith(".part"))
    output.write_bytes(b"partial")
    mode = source.read_bytes()
    if mode.startswith(b"WAIT"):
        output.with_suffix(".pid").write_text(str(os.getpid()))
        while True: time.sleep(.1)
    if mode.startswith(b"FAIL"):
        for _ in range(128): os.write(2,b"x"*8192)
        os.write(2,b"expected failure")
        sys.exit(7)
    output.write_bytes(b"completed")
"""
    )
    for name in ("mp4dump", "mp4decrypt", "ffmpeg", "ffprobe"):
        path = binary_dir / name
        path.write_text(program)
        path.chmod(0o700)
    monkeypatch.setenv(
        "PATH", str(binary_dir) + os.pathsep + os.environ.get("PATH", "")
    )
    formatter = MediaFormatter(max_workers=1, queue_entries=2, output_bytes=128)
    drm = OnlyDRM.__new__(OnlyDRM)
    drm.media_formatter = formatter
    drm.mp4dump_filepath = binary_dir / "mp4dump"
    drm.mp4decrypt_filepath = binary_dir / "mp4decrypt"
    return drm, formatter


async def wait_for_file(path):
    deadline = time.monotonic() + 3
    while not path.exists():
        if time.monotonic() > deadline:
            pytest.fail(f"Fixture subprocess did not create {path.name}")
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_encryption_marker_is_streamed_and_success_is_published_before_source_removal(
    media_tools, tmp_path
):
    drm, _ = media_tools
    source_dir = tmp_path / "folder.enc"
    source_dir.mkdir()
    source = source_dir / "video.enc.mp4"
    source.write_bytes(b"READY")
    assert await drm._is_file_encrypted_async(source)
    output = await drm.decrypt_file_async(source, "fixture")
    assert output == source_dir / "video.dec.mp4"
    assert output.read_bytes() == b"completed" and not source.exists()


@pytest.mark.asyncio
async def test_failed_decryption_preserves_source_and_bounds_error(
    media_tools, tmp_path
):
    drm, _ = media_tools
    source = tmp_path / "video.enc.mp4"
    source.write_bytes(b"FAIL")
    with pytest.raises(RuntimeError, match="expected failure") as error:
        await drm.decrypt_file_async(source, "fixture")
    assert len(str(error.value)) < 180
    assert source.read_bytes() == b"FAIL"
    assert not (tmp_path / "video.dec.part.mp4").exists()


@pytest.mark.asyncio
async def test_cancelled_decryption_stops_writes_before_cleanup(media_tools, tmp_path):
    drm, _ = media_tools
    source = tmp_path / "video.enc.mp4"
    source.write_bytes(b"WAIT")
    caller = asyncio.create_task(drm.decrypt_file_async(source, "fixture"))
    marker = tmp_path / "video.dec.part.pid"
    await wait_for_file(marker)
    pid = int(marker.read_text())
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(caller, 2)
    assert source.read_bytes() == b"WAIT"
    assert not (tmp_path / "video.dec.part.mp4").exists()
    if os.name == "posix":
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)


@pytest.mark.asyncio
async def test_failed_merge_preserves_inputs_and_worker_keeps_running(
    media_tools, tmp_path
):
    _, formatter = media_tools
    formatter.start_workers(1)
    video, audio = tmp_path / "video.mp4", tmp_path / "audio.m4a"
    video.write_bytes(b"FAIL")
    audio.write_bytes(b"READY")
    output = tmp_path / "output.mp4"
    try:
        assert not await formatter.merge(output, [video, audio])
        assert video.exists() and audio.exists() and not output.exists()
        video.write_bytes(b"READY")
        assert await formatter.merge(output, [video, audio])
        assert output.read_bytes() == b"completed"
        assert not video.exists() and not audio.exists()
    finally:
        await formatter.shutdown()
    assert all(worker.done() for worker in formatter.workers)


@pytest.mark.asyncio
async def test_active_merge_cancel_reaps_and_preserves_sources(media_tools, tmp_path):
    _, formatter = media_tools
    formatter.start_workers(1)
    video, audio = tmp_path / "video.mp4", tmp_path / "audio.m4a"
    video.write_bytes(b"WAIT")
    audio.write_bytes(b"READY")
    output = tmp_path / "output.mp4"
    caller = asyncio.create_task(formatter.merge(output, [video, audio]))
    marker = tmp_path / "output.pid"
    try:
        await wait_for_file(marker)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, 2)
        assert video.exists() and audio.exists()
        assert not output.exists() and not output.with_suffix(".part").exists()
        if os.name == "posix":
            with pytest.raises(ChildProcessError):
                os.waitpid(int(marker.read_text()), os.WNOHANG)
    finally:
        caller.cancel()
        await formatter.shutdown()


@pytest.mark.asyncio
async def test_queue_backpressure_cancelled_pending_request_and_shutdown(
    monkeypatch, tmp_path
):
    formatter = MediaFormatter(max_workers=1, queue_entries=1)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def blocked(output, paths):
        calls.append(output.name)
        started.set()
        await release.wait()
        return False

    monkeypatch.setattr(formatter, "format_media", blocked)
    formatter.start_workers(1)
    first = asyncio.create_task(formatter.merge(tmp_path / "first", []))
    await started.wait()
    queued = formatter.add_task(tmp_path / "cancelled", [])
    with pytest.raises(asyncio.QueueFull):
        formatter.add_task(tmp_path / "overflow", [])
    waiting = asyncio.create_task(formatter.merge(tmp_path / "waiting", []))
    await asyncio.sleep(0)
    assert formatter.merge_queue.qsize() == 1 and not waiting.done()
    queued.cancel()
    closing = asyncio.create_task(formatter.shutdown())
    with pytest.raises(asyncio.QueueShutDown):
        await waiting
    release.set()
    assert not await first
    await closing
    assert calls == ["first"]
    assert formatter.merge_queue.qsize() == 0


@pytest.mark.asyncio
async def test_process_admission_obeys_explicit_budget(monkeypatch):
    formatter = MediaFormatter(max_workers=3)
    release, full = asyncio.Event(), asyncio.Event()
    running = maximum = 0

    async def fake_process(*args, **kwargs):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        if running == 3:
            full.set()
        try:
            await release.wait()
            return ProcessResult(0, b"", b"", False, False)
        finally:
            running -= 1

    monkeypatch.setattr(
        "ultima_scraper_api.apis.onlyfans.classes.only_drm.run_process", fake_process
    )
    tasks = [asyncio.create_task(formatter.run_process(["fixture"])) for _ in range(8)]
    await full.wait()
    assert maximum == 3
    release.set()
    await asyncio.gather(*tasks)
    assert maximum == 3


def test_resource_values_are_independent_and_explicit_values_win(monkeypatch):
    values = {
        "ULTIMA_MEDIA_PROCESS_CONCURRENCY": "2",
        "ULTIMA_MEDIA_PROCESS_QUEUE_ENTRIES": "7",
        "ULTIMA_MEDIA_PROCESS_OUTPUT_BYTES": "89",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    configured = MediaFormatter()
    assert (
        configured.max_workers,
        configured.queue_entries,
        configured.output_bytes,
    ) == (2, 7, 89)
    explicit = MediaFormatter(11, queue_entries=13, output_bytes=4097)
    assert (explicit.max_workers, explicit.queue_entries, explicit.output_bytes) == (
        11,
        13,
        4097,
    )
    for invalid in (True, 0, -1, 1.5, "1.5"):
        with pytest.raises(ValueError, match="positive integer"):
            MediaFormatter(queue_entries=invalid)


@pytest.mark.asyncio
async def test_cancelled_single_file_copy_retains_thread_ownership(
    monkeypatch, tmp_path
):
    if sys.version_info[:3] == (3, 14, 0):
        pytest.skip(
            "The project to_thread shim is inline on 3.14.0; use patched Python"
        )
    formatter = MediaFormatter(max_workers=1)
    formatter.start_workers(1)
    started, release = threading.Event(), threading.Event()
    source, output = tmp_path / "source.mp4", tmp_path / "output.mp4"
    source.write_bytes(b"source")
    real_copy = shutil.copy

    def slow_copy(source, destination):
        real_copy(source, destination)
        started.set()
        assert release.wait(3)

    monkeypatch.setattr(shutil, "copy", slow_copy)
    caller = asyncio.create_task(formatter.merge(output, [source]))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.001)
        caller.cancel()
        await asyncio.sleep(0.01)
        assert not caller.done() and output.with_suffix(".part").exists()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, 2)
        assert source.exists() and not output.exists()
        assert not output.with_suffix(".part").exists()
    finally:
        release.set()
        await formatter.shutdown()


@pytest.mark.asyncio
async def test_cancelled_shutdown_drains_active_process_and_cancels_queue(
    media_tools, tmp_path
):
    _, formatter = media_tools
    formatter.start_workers(1)
    video, audio = tmp_path / "video.mp4", tmp_path / "audio.m4a"
    video.write_bytes(b"WAIT")
    audio.write_bytes(b"READY")
    caller = asyncio.create_task(
        formatter.merge(tmp_path / "output.mp4", [video, audio])
    )
    await wait_for_file(tmp_path / "output.pid")
    queued = formatter.add_task(tmp_path / "queued.mp4", [audio])
    closing = asyncio.create_task(formatter.shutdown())
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(closing, 2)
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert queued.cancelled()
    assert video.exists() and audio.exists()
    assert not (tmp_path / "output.part").exists()
    assert not formatter._process_tasks
    with pytest.raises(RuntimeError, match="closed"):
        await formatter.run_process(["fixture"])


@pytest.mark.asyncio
async def test_native_ffmpeg_stream_copy_and_probe(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Native FFmpeg tools are not installed")
    video, audio, output = (
        tmp_path / "video.mp4",
        tmp_path / "audio.m4a",
        tmp_path / "output.mp4",
    )
    for source, target, codec in (
        ("color=c=black:s=64x64:r=5", video, ["-c:v", "mpeg4"]),
        ("anullsrc=r=8000:cl=mono", audio, ["-c:a", "aac"]),
    ):
        result = await run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                source,
                "-t",
                "0.4",
                "-threads",
                "1",
                *codec,
                str(target),
            ]
        )
        assert result.returncode == 0, result.stderr
    formatter = MediaFormatter(max_workers=1)
    formatter.start_workers(1)
    try:
        assert await formatter.merge(output, [video, audio])
        result = await run_process(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(output),
            ]
        )
        assert result.returncode == 0
        assert b'"video"' in result.stdout and b'"audio"' in result.stdout
        assert not video.exists() and not audio.exists()
    finally:
        await formatter.shutdown()
