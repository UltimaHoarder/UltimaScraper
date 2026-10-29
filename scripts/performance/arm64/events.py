"""Consume the actual dashboard event socket during the owned workload."""

import asyncio
import json
import threading
import time
from collections import Counter

import aiohttp


class EventObserver:
    def __init__(self, port, output, started_event):
        self.port, self.output, self.started_event = port, output, started_event
        self.stop_event = threading.Event()
        self.errors = []
        self.counts = Counter()
        self.pings = self.pongs = 0
        self.maximum_pong_seconds = 0.0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        if not self.started_event.wait(900) or self.stop_event.is_set():
            return
        try:
            asyncio.run(self.observe())
        except Exception as exc:  # noqa: BLE001 - propagate observer failure to controller
            self.errors.append(repr(exc))

    async def observe(self):
        started = time.monotonic()
        next_ping = started
        pending = None
        with (self.output / "websocket.jsonl").open("w") as log:
            async with aiohttp.ClientSession() as session:  # noqa: SIM117
                async with session.ws_connect(
                    f"http://127.0.0.1:{self.port}/ws/events",
                    origin="http://127.0.0.1:2112",
                    headers={"X-USR-Admin-Token": "fixture-local-only"},
                ) as socket:
                    while not self.stop_event.is_set():
                        now = time.monotonic()
                        if pending is not None and now - pending > 50:
                            raise RuntimeError(
                                "Dashboard WebSocket pong exceeded 50 seconds"
                            )
                        if now >= next_ping and pending is None:
                            pending = now
                            await socket.send_json({"type": "ping", "timestamp": now})
                            self.pings += 1
                            next_ping = now + 25
                        try:
                            message = await asyncio.wait_for(
                                socket.receive(), timeout=1
                            )
                        except TimeoutError:
                            continue
                        if message.type != aiohttp.WSMsgType.TEXT:
                            raise RuntimeError(
                                f"Dashboard WebSocket stopped: {message.type}"
                            )
                        payload = json.loads(message.data)
                        kind = str(payload.get("type", "unknown"))
                        self.counts[kind] += 1
                        record = {
                            "elapsed": time.monotonic() - started,
                            "type": kind,
                            "bytes": len(message.data.encode()),
                        }
                        if kind == "pong":
                            assert (
                                pending is not None and payload["timestamp"] == pending
                            )
                            elapsed = time.monotonic() - pending
                            self.maximum_pong_seconds = max(
                                self.maximum_pong_seconds, elapsed
                            )
                            record["round_trip_seconds"] = elapsed
                            self.pongs += 1
                            pending = None
                        log.write(json.dumps(record) + "\n")
                        log.flush()

    def stop(self):
        self.stop_event.set()
        self.started_event.set()
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "Owned event observer did not stop"

    def verify(self):
        assert not self.errors, self.errors
        assert self.pongs >= 2, "No repeated dashboard socket heartbeats"
        assert sum(v for k, v in self.counts.items() if k != "pong") > 0
        result = {
            "types": dict(self.counts),
            "pings": self.pings,
            "pongs": self.pongs,
            "maximum_pong_seconds": self.maximum_pong_seconds,
            "errors": self.errors,
            "scope": "Real dashboard socket and JSON ping protocol; no browser-rendering claim",
        }
        (self.output / "websocket-verification.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        return result
