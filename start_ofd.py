#!/usr/bin/env python3
import asyncio
import os
import time
import traceback

import tests.main_test as main_test

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
                if domain:
                    if site_names:
                        site_name = domain
                    else:
                        print(string)
                        continue
                else:
                    print(string)
                    site_choice = str(input())
                    site_choice = int(site_choice)
                    site_name = site_names[site_choice]
                site_name_lower = site_name.lower()
                api = await main_datascraper.start_datascraper(
                    json_config, site_name_lower
                )
                if api:
                    api.close_pools()
                if exit_on_completion:
                    print("Now exiting.")
                    exit(0)
                elif not infinite_loop:
                    print("Input anything to continue")
                    input()
                elif loop_timeout:
                    print("Pausing scraper for " + loop_timeout + " seconds.")
                    time.sleep(int(loop_timeout))

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
        loop.close()
except Exception as e:
    print(traceback.format_exc())
    input()
