#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path
from sys import exit
from typing import Literal, get_args

from helpers.main_helper import OptionsFormat

parser = argparse.ArgumentParser()
parser.add_argument(
    "-v", "--verbose", help="increase output verbosity", action="store_true"
)
parsed_args = parser.parse_args()
try:
    import tests.main_test as main_test
except SyntaxError:
    version_info = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    string = f"You're executing the script with Python {version_info}. Execute the script with Python 3.10.1+"
    print(string)
    exit()
main_test.version_check()
main_test.check_config()
main_test.check_profiles()

if __name__ == "__main__":
    import apis.api_helper as api_helper
    import datascraper.main_datascraper as main_datascraper
    import helpers.main_helper as main_helper

    api_helper.parsed_args = parsed_args

    config_path = Path(".settings", "config.json")
    config, _updated = main_helper.get_config(config_path)
    global_settings = config.settings
    exit_on_completion = global_settings.exit_on_completion
    infinite_loop = global_settings.infinite_loop
    loop_timeout = global_settings.loop_timeout
    domain = global_settings.auto_site_choice
    json_sites = config.supported
    string, site_names_ = main_helper.module_chooser(domain, json_sites.__dict__)
    site_name_literals = Literal["OnlyFans", "Fansly", "StarsAVN"]
    site_names: list[site_name_literals] = list(get_args(site_name_literals))
    # logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    async def main():
        while True:
            site_options = OptionsFormat(site_names, "sites", domain)
            for site_name in site_options.final_choices:
                api = await main_datascraper.start_datascraper(config, site_name)
                if api:
                    api.close_pools()
                    await asyncio.sleep(1)
            if exit_on_completion:
                print("Now exiting.")
                break
            elif not infinite_loop:
                print("Input anything to continue")
                input()
            elif loop_timeout:
                print(f"Pausing scraper for {loop_timeout} seconds.")
                await asyncio.sleep(float(loop_timeout))

    asyncio.run(main())
