#!/usr/bin/env python3
import sys
import asyncio
import os
import traceback

from rich import panel
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

try:
    import tests.main_test as main_test
except SyntaxError:
    print("Execute the script with Python 3.10\nPress enter to continue")
    exit()
try:

    main_test.version_check()
    main_test.check_config()
    main_test.check_profiles()

    if __name__ == "__main__":
        import datascraper.main_datascraper as main_datascraper
        import helpers.main_helper as main_helper

        config_path = os.path.join(".settings", "config.json")
        json_config, json_config2 = main_helper.get_config(config_path)
        json_settings = json_config["settings"]
        exit_on_completion = json_settings["exit_on_completion"]
        infinite_loop = json_settings["infinite_loop"]
        loop_timeout = json_settings["loop_timeout"]
        json_sites = json_config["supported"]
        domain = json_settings["auto_site_choice"]
        string, site_names = main_helper.module_chooser(domain, json_sites)

        # logging.basicConfig(level=logging.DEBUG, format="%(message)s")
        async def main():
            while True:

                class live_display:
                    def __init__(self) -> None:
                        self.layout = Layout()
                        self.layout.split_column(
                            Layout(Text(" "), name="blank", size=1),
                            Layout(
                                Panel("", padding=1, title="N/A"), name="header", size=3
                            ),
                            Layout(name="upper"),
                            Layout(Panel(Text(), title="TEXT"), name="lower", size=3),
                        )
                        self.layout["upper"].split_row(
                            Layout(Panel("", title="N/A"), name="left"),
                            Layout(Panel("", title="N/A"), name="right", ratio=2),
                        )
                        self.live = Live(self.layout, refresh_per_second=4)
                        self.panels = self._panels(self.layout)

                    class _panels:
                        def __init__(self, layout: Layout) -> None:
                            self.header = layout["header"]
                            self.options = layout["upper"]["left"].renderable
                            self.body = True
                            self.text = True

                        def update_option_text(self, text: str):
                            self.options.renderable = text

                # l_d = live_display()
                if domain:
                    if site_names:
                        site_name = domain
                    else:
                        print(string)
                        continue
                else:
                    # l_d.panels.update_option_text(string)
                    print(string)
                    try:
                        site_choice = str(input())
                        site_choice = int(site_choice)
                        site_name = site_names[site_choice]
                    except (ValueError, IndexError):
                        continue
                site_name_lower = site_name.lower()
                api = await main_datascraper.start_datascraper(
                    json_config, site_name_lower
                )
                if api:
                    api.close_pools()
                if exit_on_completion:
                    print("Now exiting.")
                    break
                elif not infinite_loop:
                    print("Input anything to continue")
                    input()
                elif loop_timeout:
                    print("Pausing scraper for " + loop_timeout + " seconds.")
                    await asyncio.sleep(float(loop_timeout))

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        asyncio.run(main())
except Exception as e:
    print(traceback.format_exc())
    input()
