#!/usr/bin/env python3
import argparse
import asyncio
from typing import Literal, get_args

parser = argparse.ArgumentParser()
parser.add_argument(
    "-v", "--verbose", help="increase output verbosity", action="store_true"
)
parsed_args = parser.parse_args()
from tests import main_test

main_test.check_start_up()

# Main execution block
if __name__ == "__main__":
    # Import necessary modules
    import ultima_scraper_api.apis.api_helper as api_helper
    import ultima_scraper_api.helpers.main_helper as main_helper
    from ultima_scraper_collection.managers.filesystem_manager import FilesystemManager

    from ultima_scraper.ultima_scraper import UltimaScraper

    # Pass parsed arguments to API helper
    api_helper.parsed_args = parsed_args
    # Initialize FilesystemManager
    fsm = FilesystemManager()
    # Define path to config file
    config_path = fsm.settings_directory.joinpath("config.json")
    # Load configuration and global settings
    config, _updated = main_helper.get_config(config_path)
    global_settings = config.settings
    # Extract relevant settings
    exit_on_completion = global_settings.exit_on_completion
    infinite_loop = global_settings.infinite_loop
    loop_timeout = global_settings.loop_timeout
    domain = global_settings.auto_site_choice
    json_sites = config.supported
    # Choose modules based on domain and supported sites
    string, site_names_ = main_helper.module_chooser(domain, json_sites.__dict__)
    # Define available site names
    site_name_literals = Literal["OnlyFans", "Fansly"]
    site_names: list[site_name_literals] = list(get_args(site_name_literals))
    # # Configure logging (currently commented out)
    # logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    # Initialize UltimaScraper with global settings
    USR = UltimaScraper(global_settings)

    # Asynchronous function to run the scraper
    async def main():
        # Main loop for scraping
        while True:
            # Create site selection options
            site_options = await USR.option_manager.create_option(
                site_names, "sites", domain
            )
            # Iterate through selected sites
            for site_name in site_options.final_choices:
                # Start the scraper for the current site
                _api = await USR.start(
                    config,
                    site_name,
                )
            # Handle post-scraping actions based on settings
            if exit_on_completion:
                # Close API pools if exiting on completion
                for datascraper in USR.datascraper_manager.datascrapers:
                    await datascraper.api.close_pools()
                await USR.ui_manager.display("Now exiting")
                break
            elif not infinite_loop:
                # Wait for user input if not in infinite loop
                await USR.ui_manager.display("Input anything to continue")
                input()
            elif loop_timeout:
                # Pause if loop timeout is set
                await USR.ui_manager.display(
                    f"Pausing scraper for {loop_timeout} seconds"
                )
                await asyncio.sleep(float(loop_timeout))

    # Run the main asynchronous function
    asyncio.run(main())
