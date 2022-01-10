import timeit
from typing import Any, Optional

import apis.fansly.classes as fansly_classes
import apis.onlyfans.classes as onlyfans_classes
import apis.starsavn.classes as starsavn_classes
import helpers.main_helper as main_helper
import modules.fansly as m_fansly
import modules.onlyfans as m_onlyfans
import modules.starsavn as m_starsavn
from apis.fansly import fansly as Fansly
from apis.onlyfans import onlyfans as OnlyFans
from apis.starsavn import starsavn as StarsAVN
from classes.make_settings import Config
from helpers.main_helper import OptionsFormat, account_setup

auth_types = (
    onlyfans_classes.auth_model.create_auth
    | fansly_classes.auth_model.create_auth
    | starsavn_classes.auth_model.create_auth
)
user_types = (
    onlyfans_classes.user_model.create_user
    | fansly_classes.user_model.create_user
    | starsavn_classes.user_model.create_user
)
api_helper = OnlyFans.api_helper


async def start_datascraper(
    json_config: dict[Any, Any],
    site_name_lower: str,
    api_: Optional[OnlyFans.start | Fansly.start | StarsAVN.start] = None,
    webhooks: bool = True,
):
    json_settings = json_config["settings"]
    main_helper.assign_vars(json_config)

    proxies: list[str] = await api_helper.test_proxies(json_settings["proxies"])
    if json_settings["proxies"] and not proxies:
        print("Unable to create session")
        return None

    async def default(
        datascraper: m_onlyfans.OnlyFansDataScraper
        | m_fansly.FanslyDataScraper
        | m_starsavn.StarsAVNDataScraper,
    ):
        api = datascraper.api
        site_settings = api.get_site_settings()
        if not site_settings:
            return
        subscription_array: list[user_types] = []
        auth_count = 0
        profile_options = OptionsFormat(
            api.auths, "profiles", site_settings.auto_profile_choice
        )
        api.auths = profile_options.final_choices
        for auth in api.auths:
            auth: auth_types = auth
            if not auth.auth_details:
                continue
            setup = False
            setup, subscriptions = await account_setup(
                auth,
                datascraper,
                site_settings,
            )
            if not setup:
                if webhooks:
                    await main_helper.process_webhooks(api, "auth_webhook", "failed")
                auth_details: dict[str, Any] = {}
                auth_details["auth"] = auth.auth_details.export()
                profile_directory = auth.directory_manager.profile.root_directory
                user_auth_filepath = profile_directory.joinpath("auth.json")
                main_helper.export_data(auth_details, user_auth_filepath)
                continue
            auth_count += 1
            subscription_array.extend(subscriptions)
            await main_helper.process_webhooks(api, "auth_webhook", "succeeded")
            # Do stuff with authed user
        subscription_options = OptionsFormat(
            subscription_array, "subscriptions", site_settings.auto_model_choice
        )
        subscription_list = subscription_options.final_choices
        if site_settings.jobs.scrape.paid_content and api.has_active_auths():
            print("Scraping Paid Content")
            for authed in api.auths:
                await datascraper.paid_content_scraper(authed)
        if site_settings.jobs.scrape.subscriptions and api.has_active_auths():
            print("Scraping Subscriptions")
            await main_helper.process_jobs(
                datascraper,
                subscription_list,
            )
        await main_helper.process_downloads(api, datascraper)
        if webhooks:
            await main_helper.process_webhooks(api, "download_webhook", "succeeded")

    archive_time = timeit.default_timer()
    match site_name_lower:
        case "onlyfans":
            if not isinstance(api_, OnlyFans.start):
                api_ = OnlyFans.start(
                    max_threads=json_settings["max_threads"],
                    config=Config(**json_config),
                )
                main_helper.process_profiles(json_settings, proxies, api_)
            datascraper = m_onlyfans.OnlyFansDataScraper(api_)
            await default(datascraper)
        case "fansly":
            if not isinstance(api_, Fansly.start):
                api_ = Fansly.start(
                    max_threads=json_settings["max_threads"],
                    config=Config(**json_config),
                )
                main_helper.process_profiles(json_settings, proxies, api_)
            datascraper = m_fansly.FanslyDataScraper(api_)
            await default(datascraper)
        case "starsavn":
            if not isinstance(api_, StarsAVN.start):
                api_ = StarsAVN.start(
                    max_threads=json_settings["max_threads"],
                    config=Config(**json_config),
                )
                main_helper.process_profiles(json_settings, proxies, api_)
            datascraper = m_starsavn.StarsAVNDataScraper(api_)
            await default(datascraper)
    stop_time = str(int(timeit.default_timer() - archive_time) / 60)[:4]
    print("Archive Completed in " + stop_time + " Minutes")
    return api_
