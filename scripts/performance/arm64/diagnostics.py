"""Opt-in stack and event-loop sampling inside the disposable benchmark only."""

import asyncio
import contextlib
import json
import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path

import psutil


def stack(frame):
    frames = []
    while frame is not None and len(frames) < 32:
        frames.append(
            {
                "file": frame.f_code.co_filename,
                "function": frame.f_code.co_name,
                "line": frame.f_lineno,
            }
        )
        frame = frame.f_back
    return frames


def install():
    directory = Path(os.environ["FIXTURE_METRICS_DIR"])
    process = multiprocessing.current_process().name
    lock = threading.Lock()
    output = (directory / f"diagnostics-{os.getpid()}.jsonl").open("a", buffering=1)

    def record(event, **values):
        with lock:
            output.write(
                json.dumps(
                    {
                        "event": event,
                        "monotonic": time.monotonic(),
                        "time": time.time(),
                        "pid": os.getpid(),
                        "process": process,
                        **values,
                    }
                )
                + "\n"
            )

    def sample_threads():
        sampler_id = threading.get_ident()
        while True:
            cpu = {
                row.id: row.user_time + row.system_time
                for row in psutil.Process().threads()
            }
            names = {thread.ident: thread for thread in threading.enumerate()}
            for ident, frame in sys._current_frames().items():
                if ident == sampler_id:
                    continue
                thread = names.get(ident)
                record(
                    "thread",
                    thread=thread.name if thread else str(ident),
                    native_id=thread.native_id if thread else None,
                    cpu_seconds=cpu.get(thread.native_id) if thread else None,
                    stack=stack(frame),
                )
            time.sleep(2)

    threading.Thread(
        target=sample_threads, name="benchmark-stack-sampler", daemon=True
    ).start()

    # Patch only the ASGI process. Writer and scraper samples use the same clock.
    if process != "ultima-control":
        return

    import uvicorn

    original_load = uvicorn.Config.load

    def load(config):
        original_load(config)
        application = config.loaded_app

        async def measured(scope, receive, send):
            if scope["type"] != "http":
                return await application(scope, receive, send)
            path = scope["path"]  # Deliberately omit query strings and bodies.
            method = scope["method"]
            request = id(scope)
            started = time.monotonic()
            record("request_start", request=request, method=method, path=path)
            try:
                return await application(scope, receive, send)
            finally:
                record(
                    "request_end",
                    request=request,
                    method=method,
                    path=path,
                    seconds=time.monotonic() - started,
                )

        config.loaded_app = measured

    uvicorn.Config.load = load
    original_serve = uvicorn.Server.serve

    async def sample_loop():
        loop = asyncio.get_running_loop()
        previous = loop.time()
        while True:
            await asyncio.sleep(5)
            now = loop.time()
            tasks = []
            for task in asyncio.all_tasks():
                if task is asyncio.current_task():
                    continue
                chain = []
                coroutine = task.get_coro()
                for _ in range(24):
                    frame = getattr(
                        coroutine, "cr_frame", getattr(coroutine, "gi_frame", None)
                    )
                    if frame is not None:
                        chain.append(stack(frame)[0])
                    coroutine = getattr(
                        coroutine, "cr_await", getattr(coroutine, "gi_yieldfrom", None)
                    )
                    if coroutine is None:
                        break
                tasks.append({"name": task.get_name(), "stack": chain})
            record("loop", lag_seconds=max(0, now - previous - 5), tasks=tasks)
            previous = now

    async def serve(server, *args, **kwargs):
        monitor = asyncio.create_task(sample_loop(), name="benchmark-loop-sampler")
        try:
            return await original_serve(server, *args, **kwargs)
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor

    uvicorn.Server.serve = serve
