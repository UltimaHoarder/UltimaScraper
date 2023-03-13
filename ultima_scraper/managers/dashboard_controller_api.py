import asyncio
from typing import Any

import orjson
import ultima_scraper_api
import websockets
from ultima_scraper_api.apis.background_tasks import BackgroundTask
from websockets.legacy.client import WebSocketClientProtocol

user_types = ultima_scraper_api.user_types

from ultima_scraper_api.classes.make_settings import Config


class DashboardControllerAPI:
    def __init__(self, config: Config) -> None:
        self.listener_args = (
            self.handler,
            config.settings.tui.host,
            config.settings.tui.port,
        )
        self.CONNECTIONS: dict[str, WebSocketClientProtocol] = {}
        self.background_task = BackgroundTask()
        self.background_task.create_background_task(self.start_websocket)
        _task = asyncio.create_task(self.worker())
        self.prompt_queue: asyncio.Queue[Any] = asyncio.Queue()
        _blocking = self.wait_for_connection()

    async def start_websocket(self, kwargs: dict[str, Any] = {}):
        await self.listener()

    async def listener(self):
        async with websockets.serve(*self.listener_args):  # type: ignore
            await asyncio.Future()

    def wait_for_connection(self):
        found_connections = False
        while not found_connections:
            if self.CONNECTIONS:
                found_connections = True
        return found_connections

    async def handler(self, websocket: WebSocketClientProtocol):
        self.CONNECTIONS[websocket.id.hex] = websocket
        _reader_task = asyncio.create_task(self.reader(websocket))
        try:
            await websocket.wait_closed()
        finally:
            self.CONNECTIONS.pop(websocket.id.hex)

    async def reader(self, websocket: WebSocketClientProtocol):
        # Server crashes when GUI closes on a prompt/or is waiting for response
        async for message in websocket:
            data = orjson.loads(message)
            match data["type"]:
                case "prompt":
                    await self.prompt_queue.put(data)
                case _:
                    pass

    async def worker(self):
        while True:
            _item = await self.background_task.queue.get()
            pass

    async def message_all(self, data: Any):
        self.wait_for_connection()
        websockets.broadcast([*self.CONNECTIONS.values()], data)  # type: ignore

    async def prompt(self, string: str) -> str:
        data = orjson.dumps({"type": "prompt", "value": string})
        await self.message_all(data)
        # old_connections = self.CONNECTIONS.copy()
        while True:
            if self.prompt_queue.qsize():
                response = await self.prompt_queue.get()
                return str(response["value"])
            # If no clients, we'll retry prompt
            # Still need to find a way to send the prompt to connections that join after
            if not self.CONNECTIONS:
                return await self.prompt(string)

    async def change_title(self, string: str):
        data = orjson.dumps({"type": "change_title", "value": string})
        await self.message_all(data)

    async def datatable_monitor(self, subscription_list: list[user_types]):
        while True:
            data_byte_array: list[str] = [
                x.convert_to_dill().hex() for x in subscription_list
            ]
            data = orjson.dumps({"type": "datatable_monitor", "value": data_byte_array})
            await self.message_all(data)
            await asyncio.sleep(1)

    # async def convert_object_to_dill(self, parent: dict[str, Any], key: str, data: Any):
    #     test = parent.__dict__.copy()
    #     test["dashboard_controller_api"] = None
    #     new = []
    #     for x in data:
    #         if not isinstance(x, str):
    #             x = x.convert_to_dill()
    #         new.append(x)
    #         pass
    #     test[key] = new
    #     ok: str = dill.dumps(test).hex()
    #     return ok
