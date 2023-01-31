import asyncio
import timeit
from typing import Any

import ultima_scraper_api
import ultima_scraper_api.helpers.main_helper as main_helper
from ultima_scraper_api.apis import api_helper
from ultima_scraper_api.apis.dashboard_controller_api import DashboardControllerAPI
from ultima_scraper_api.apis.fansly import fansly as Fansly
from ultima_scraper_api.apis.onlyfans import onlyfans as OnlyFans
from ultima_scraper_api.classes.make_settings import Config
from ultima_scraper_api.helpers.main_helper import OptionsFormat

import ultima_scraper.modules.fansly as m_fansly
import ultima_scraper.modules.onlyfans as m_onlyfans

auth_types = ultima_scraper_api.auth_types
user_types = ultima_scraper_api.user_types


async def start_datascraper(
    config: Config,
    site_name: str,
    api_: OnlyFans.start | Fansly.start | None = None,
    webhooks: bool = True,
    dashboard_controller_api: DashboardControllerAPI | None = None,
):
    global_settings = config.settings

    proxies: list[str] = await api_helper.test_proxies(global_settings.proxies)
    if global_settings.proxies and not proxies:
        print("Unable to create session")
        return None

    async def default(
        datascraper: m_onlyfans.OnlyFansDataScraper | m_fansly.FanslyDataScraper,
    ):
        datascraper.dashboard_controller_api = dashboard_controller_api
        api = datascraper.api
        if api.filesystem_manager.directory_manager:
            api.filesystem_manager.directory_manager.create_directories()
        api.dashboard_controller_api = dashboard_controller_api
        global_settings = api.get_global_settings()
        site_settings = api.get_site_settings()
        if not (global_settings and site_settings):
            return
        if api.dashboard_controller_api:
            await api.dashboard_controller_api.change_title(api.site_name)
        await main_helper.process_profiles(api, global_settings)
        subscription_array: list[user_types] = []
        auth_count = 0
        profile_options = await OptionsFormat(
            api.auths,
            "profiles",
            site_settings.auto_profile_choice,
            datascraper.api.dashboard_controller_api,
        ).formatter()
        api.auths = profile_options.final_choices
        # await dashboard_controller.update_main_table(api)
        identifiers = []
        if site_settings.auto_model_choice:
            subscription_options = await OptionsFormat(
                subscription_array,
                "subscriptions",
                site_settings.auto_model_choice,
                datascraper.api.dashboard_controller_api,
            ).formatter()
            if not subscription_options.scrape_all():
                identifiers = subscription_options.choice_list
        for auth in api.auths:
            auth: auth_types = auth
            if not auth.auth_details:
                continue
            setup = False
            setup, subscriptions = await datascraper.account_setup(
                auth, datascraper, site_settings, identifiers
            )
            if not setup:
                if webhooks:
                    await main_helper.process_webhooks(
                        api, "auth_webhook", "failed", global_settings
                    )
                auth_details: dict[str, Any] = {}
                auth_details["auth"] = auth.auth_details.export()
                profiles_directory = api.filesystem_manager.profiles_directory
                user_auth_filepath = profiles_directory.joinpath(
                    api.site_name, auth.auth_details.username, "auth.json"
                )
                main_helper.export_json(auth_details, user_auth_filepath)
                continue
            auth_count += 1
            subscription_array.extend(subscriptions)
            await main_helper.process_webhooks(
                api, "auth_webhook", "succeeded", global_settings
            )
            # Do stuff with authed user
        subscription_options = await OptionsFormat(
            subscription_array,
            "subscriptions",
            site_settings.auto_model_choice,
            datascraper.api.dashboard_controller_api,
        ).formatter()
        datascraper.subscription_options = subscription_options
        job_user_list = subscription_options.final_choices
        if api.dashboard_controller_api:
            intask = api.dashboard_controller_api.datatable_monitor(job_user_list)
            _task = asyncio.create_task(intask)
        await datascraper.start_datascraper(job_user_list)
        # if global_settings.helpers.delete_empty_directories:
        #     for job_user in job_user_list:
        #         await main_helper.delete_empty_directories(
        #             job_user.directory_manager.user.download_directory,
        #             datascraper.api.filesystem_manager,
        #         )
        if webhooks:
            await main_helper.process_webhooks(
                api, "download_webhook", "succeeded", global_settings
            )

    archive_time = timeit.default_timer()
    if not api_:
        api_ = ultima_scraper_api.select_api(site_name, config)
        api_.filesystem_manager.activate_directory_manager(api_)

    datascraper = None
    if type(api_) == OnlyFans.start:
        if isinstance(api_, OnlyFans.start):
            datascraper = m_onlyfans.OnlyFansDataScraper(api_)
    elif type(api_) == Fansly.start:
        if isinstance(api_, Fansly.start):
            datascraper = m_fansly.FanslyDataScraper(api_)

    if datascraper:
        await default(datascraper)
    stop_time = str(int(timeit.default_timer() - archive_time) / 60)[:4]
    print("Archive Completed in " + stop_time + " Minutes")
    return api_
