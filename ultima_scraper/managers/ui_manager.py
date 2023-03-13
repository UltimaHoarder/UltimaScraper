import asyncio
from typing import Any

from ultima_scraper.managers.dashboard_controller_api import DashboardControllerAPI


class UiManager:
    # Will use this to display things to the terminal in the future
    def __init__(self) -> None:
        self.mode: str = "standard"
        self.dashboard_controller_api: DashboardControllerAPI | None = None

    async def display(self, data: Any):
        match self.mode:
            case "standard":
                print(data)
            case "dashboard":
                if self.dashboard_controller_api:
                    intask = self.dashboard_controller_api.datatable_monitor(data)
                    _task = asyncio.create_task(intask)
                pass
            case _:
                pass
