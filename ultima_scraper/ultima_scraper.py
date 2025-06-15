import asyncio
import timeit
from typing import Any

import ultima_scraper_api
import ultima_scraper_api.classes.make_settings as make_settings
import ultima_scraper_api.helpers.main_helper as main_helper
import ultima_scraper_collection.managers.datascraper_manager.datascrapers.fansly as m_fansly
import ultima_scraper_collection.managers.datascraper_manager.datascrapers.onlyfans as m_onlyfans
from ultima_scraper_api.apis.onlyfans.classes.only_drm import OnlyDRM
from ultima_scraper_api.classes.make_settings import Config, Settings
from ultima_scraper_api.managers.job_manager.jobs.custom_job import CustomJob
from ultima_scraper_collection.managers.datascraper_manager.datascraper_manager import (
    DataScraperManager,
)
from ultima_scraper_collection.managers.metadata_manager.metadata_manager import (
    MetadataManager,
)
from ultima_scraper_collection.managers.option_manager import OptionManager

from ultima_scraper.managers.ui_manager import UiManager

api_types = ultima_scraper_api.api_types
auth_types = ultima_scraper_api.auth_types
user_types = ultima_scraper_api.user_types


# Main class for the UltimaScraper application
class UltimaScraper:
    # Initializes the UltimaScraper class
    # Args:
    #     settings (Settings, optional): Application settings. Defaults to Settings().
    def __init__(self, settings: Settings = Settings()) -> None:
        # Manages user interface interactions
        self.ui_manager = UiManager()
        # Manages user options and choices
        self.option_manager = OptionManager()
        # Manages datascapers for different sites
        self.datascraper_manager = DataScraperManager()
        # Stores application settings
        self.settings = settings

    async def start(
        self,
        config: Config,
        site_name: str,
        api_: api_types | None = None,
    ):
        # Starts the scraping process for a given site.
        # Args:
        #     config (Config): Configuration for the scraper.
        #     site_name (str): Name of the site to scrape (e.g., "onlyfans", "fansly").
        #     api_ (api_types | None, optional): Pre-selected API object. Defaults to None.
        archive_time = timeit.default_timer()
        # Select API if not provided
        if not api_:
            api_ = ultima_scraper_api.select_api(site_name, config)

        # Select datascraper for the chosen API
        datascraper = self.datascraper_manager.select_datascraper(
            api_, self.option_manager
        )
        if datascraper:
            # Activate directory manager for the datascraper
            datascraper.filesystem_manager.activate_directory_manager(api_)
            # Start the datascraper
            await self.start_datascraper(datascraper)
        # Calculate and display the total time taken for archiving
        stop_time = str(int(timeit.default_timer() - archive_time) / 60)[:4]
        await self.ui_manager.display(f"Archive Completed in {stop_time} Minutes")
        return api_

    async def start_datascraper(
        self,
        datascraper: m_onlyfans.OnlyFansDataScraper | m_fansly.FanslyDataScraper,
    ):
        # Starts the datascraping process for a specific datascraper.
        # This method handles authentication, profile processing, and job assignment.
        # Args:
        #     datascraper (m_onlyfans.OnlyFansDataScraper | m_fansly.FanslyDataScraper): The datascraper to use.
        api = datascraper.api
        webhooks = self.settings.webhooks
        # Create directories if a directory manager exists
        if datascraper.filesystem_manager.directory_manager:
            datascraper.filesystem_manager.directory_manager.create_directories()
        global_settings = api.get_global_settings()
        site_settings = api.get_site_settings()
        # Return if global or site settings are missing
        if not (global_settings and site_settings):
            return
        # Process user profiles
        await self.process_profiles(api, global_settings)
        scrapable_users: list[user_types] = []
        auth_count = 0
        # Create profile options based on auto_profile_choice setting
        profile_options = await self.option_manager.create_option(
            api.auths, "profiles", site_settings.auto_profile_choice
        )
        api.auths = profile_options.final_choices
        # await dashboard_controller.update_main_table(api)
        identifiers = []
        # Create subscription options if auto_model_choice is enabled
        if site_settings.auto_model_choice:
            subscription_options = await self.option_manager.create_option(
                scrapable_users, "subscriptions", site_settings.auto_model_choice
            )
            if not subscription_options.scrape_all():
                identifiers = subscription_options.return_auto_choice()
            self.option_manager.performer_options = subscription_options
        # Iterate through authentications
        for auth in api.auths:
            auth: auth_types = auth
            # Skip if auth details are missing
            if not auth.get_auth_details():
                continue
            setup = False
            # Perform account setup for the datascraper
            setup, _subscriptions = await datascraper.account_setup(
                auth, datascraper, site_settings, identifiers
            )
            if not setup:
                # Process webhooks for failed authentication
                if webhooks:
                    await main_helper.process_webhooks(
                        api, "auth_webhook", "failed", global_settings
                    )
                auth_details: dict[str, Any] = {}
                auth_details["auth"] = auth.get_auth_details().export()
                profiles_directory = datascraper.filesystem_manager.profiles_directory
                _user_auth_filepath = profiles_directory.joinpath(
                    api.site_name, auth.get_auth_details().username, "auth.json"
                )
                # main_helper.export_json(auth_details, user_auth_filepath)
                continue
            auth_count += 1
            # Extend scrapable users list
            scrapable_users.extend(await auth.get_scrapable_users())
            # Process webhooks for successful authentication
            await main_helper.process_webhooks(
                api, "auth_webhook", "succeeded", global_settings
            )
            # Handle DRM if not already set
            if not auth.drm:
                device_client_id_blob_path = (
                    datascraper.filesystem_manager.devices_directory.joinpath(
                        "device_client_id_blob"
                    )
                )
                device_private_key_path = (
                    datascraper.filesystem_manager.devices_directory.joinpath(
                        "device_private_key"
                    )
                )
                if (
                    device_client_id_blob_path.exists()
                    and device_private_key_path.exists()
                ):
                    auth.drm = OnlyDRM(
                        device_client_id_blob_path,
                        device_private_key_path,
                        auth,
                    )
        # Remove invalid authentications
        await api.remove_invalid_auths()
        # Create subscription options
        subscription_options = await self.option_manager.create_option(
            scrapable_users, "subscriptions", site_settings.auto_model_choice
        )
        self.option_manager.subscription_options = subscription_options
        # Configure datascraper jobs and get the final list of users for jobs
        final_job_user_list = await datascraper.configure_datascraper_jobs()
        # Assign jobs to users
        await self.assign_jobs(final_job_user_list)
        # Process all assigned jobs
        await datascraper.datascraper.api.job_manager.process_jobs()
        # # Optional: Delete empty directories after processing
        # if global_settings.helpers.delete_empty_directories:
        #     for job_user in job_user_list:
        #         await main_helper.delete_empty_directories(
        #             job_user.directory_manager.user.download_directory,
        #             datascraper.api.filesystem_manager,
        #         )
        # Process webhooks for download completion
        if webhooks:
            await main_helper.process_webhooks(
                api, "download_webhook", "succeeded", global_settings
            )

    async def process_profiles(
        self,
        api: api_types,
        global_settings: make_settings.Settings,
    ):
        # Processes user profiles found in the profile directory.
        # It reads authentication details from JSON files, logs in, and updates auth details.
        # Args:
        #     api (api_types): The API object for the site.
        #     global_settings (make_settings.Settings): Global application settings.
        from ultima_scraper_collection.managers.filesystem_manager import (
            FilesystemManager,
        )

        site_name = api.site_name
        filesystem_manager = FilesystemManager()
        # Construct profile directory path
        profile_directory = filesystem_manager.profiles_directory.joinpath(site_name)
        profile_directory.mkdir(parents=True, exist_ok=True)
        # Get list of user profile directories
        temp_users = list(filter(lambda x: x.is_dir(), profile_directory.iterdir()))
        temp_users = filesystem_manager.remove_mandatory_files(temp_users)
        # Iterate through user profiles
        for user_profile in temp_users:
            user_auth_filepath = user_profile.joinpath("auth.json")
            temp_json_auth = main_helper.import_json(user_auth_filepath)
            json_auth = temp_json_auth.get("auth", {})
            # Skip if profile is not active
            if not json_auth.get("active", None):
                continue
            json_auth["username"] = user_profile.name
            # Attempt to login with stored auth details
            authed = await api.login(json_auth)
            # Add proxies to session manager
            authed.session_manager.add_proxies(global_settings.proxies)
            datas = {"auth": authed.get_auth_details().export()}
            # Export updated auth details
            if datas:
                main_helper.export_json(datas, user_auth_filepath)
        return api

    async def assign_jobs(self, user_list: set[user_types]):
        # Assigns scraping and downloading jobs to a list of users.
        # Args:
        #     user_list (set[user_types]): A set of user objects to assign jobs to.
        datascraper = self.datascraper_manager.active_datascraper
        if not datascraper:
            return
        await self.ui_manager.display("Assigning Jobs")
        filesystem_manager = datascraper.filesystem_manager
        JBM = datascraper.api.job_manager
        site_settings = datascraper.api.get_site_settings()
        content_types = datascraper.api.ContentTypes()
        content_types_keys = content_types.get_keys()
        media_types = datascraper.api.MediaTypes()
        media_types_keys = media_types.get_keys()

        # Iterate through each user to assign jobs
        for user in user_list:
            # Create directory manager and format directories for the user
            await filesystem_manager.create_directory_manager(datascraper.api, user)
            await filesystem_manager.format_directories(user)
            # Initialize metadata manager and process legacy metadata
            metadata_manager = MetadataManager(user, filesystem_manager)
            await metadata_manager.process_legacy_metadata()
            datascraper.metadata_manager_users[user.id] = metadata_manager

            local_jobs: list[CustomJob] = []
            # Determine API choices for content scraping
            auto_api_choice = (
                site_settings.auto_api_choice
                if not user.scrape_whitelist
                else user.scrape_whitelist
            )

            # Create content scraping options
            content_options = await self.option_manager.create_option(
                content_types_keys, "contents", auto_api_choice
            )
            # Create scraping jobs
            jobs = JBM.create_jobs(
                "Scrape",
                content_options.final_choices,
                datascraper.prepare_scraper,
                [user, metadata_manager],
            )
            local_jobs.extend(jobs)
            # Create downloading jobs
            jobs = JBM.create_jobs(
                "Download",
                content_options.final_choices,
                datascraper.prepare_downloads,
                [user],
            )
            local_jobs.extend(jobs)

            user.jobs.extend(local_jobs)

            # Create media type options for downloads
            media_options = await self.option_manager.create_option(
                media_types_keys, "medias", site_settings.auto_media_choice
            )
            JBM.add_media_type_to_jobs(media_options.final_choices)

            # Add jobs to the job manager's queue
            for local_job in local_jobs:
                JBM.queue.put_nowait(local_job)
            await asyncio.sleep(0)
        pass
