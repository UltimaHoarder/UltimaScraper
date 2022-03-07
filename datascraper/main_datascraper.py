import timeit
from typing import Any, Optional
from apis import api_helper

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


async def start_datascraper(
    config: Config,
    site_name: str,
    api_: Optional[OnlyFans.start | Fansly.start | StarsAVN.start] = None,
    webhooks: bool = True,
):
    global_settings = config.settings

    proxies: list[str] = await api_helper.test_proxies(global_settings.proxies)
    if global_settings.proxies and not proxies:
        print("Unable to create session")
        return None

    async def default(
        datascraper: Optional[m_onlyfans.OnlyFansDataScraper]
        | Optional[m_fansly.FanslyDataScraper]
        | Optional[m_starsavn.StarsAVNDataScraper],
    ):
        if not datascraper:
            return
        api = datascraper.api
        global_settings = api.get_global_settings()
        site_settings = api.get_site_settings()
        if not (global_settings and site_settings):
            return
        await main_helper.process_profiles(api, global_settings)
        subscription_array: list[user_types] = []
        auth_count = 0
        profile_options = OptionsFormat(
            api.auths, "profiles", site_settings.auto_profile_choice
        )
        api.auths = profile_options.final_choices
        identifiers = []
        if site_settings.auto_model_choice:
            subscription_options = OptionsFormat(
                subscription_array, "subscriptions", site_settings.auto_model_choice
            )
            if not subscription_options.scrape_all():
                identifiers = subscription_options.choice_list
        for auth in api.auths:
            auth: auth_types = auth
            if not auth.auth_details:
                continue
            setup = False
            setup, subscriptions = await account_setup(
                auth, datascraper, site_settings, identifiers
            )
            if not setup:
                if webhooks:
                    await main_helper.process_webhooks(
                        api, "auth_webhook", "failed", global_settings
                    )
                auth_details: dict[str, Any] = {}
                auth_details["auth"] = auth.auth_details.export()
                profile_directory = api.base_directory_manager.profile.root_directory
                user_auth_filepath = profile_directory.joinpath(
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
        subscription_options = OptionsFormat(
            subscription_array, "subscriptions", site_settings.auto_model_choice
        )
        datascraper.subscription_options = subscription_options
        subscription_list = subscription_options.final_choices
        await main_helper.process_jobs(datascraper, subscription_list, site_settings)
        await main_helper.process_downloads(api, datascraper, global_settings)
        if webhooks:
            await main_helper.process_webhooks(
                api, "download_webhook", "succeeded", global_settings
            )

    archive_time = timeit.default_timer()
    datascraper = None
    match site_name:
        case "OnlyFans":
            if not isinstance(api_, OnlyFans.start):
                api_ = OnlyFans.start(
                    config=config,
                )
            datascraper = m_onlyfans.OnlyFansDataScraper(api_)
        case "Fansly":
            if not isinstance(api_, Fansly.start):
                api_ = Fansly.start(
                    config=config,
                )
            datascraper = m_fansly.FanslyDataScraper(api_)
        case "StarsAVN":
            if not isinstance(api_, StarsAVN.start):
                api_ = StarsAVN.start(
                    config=config,
                )
            datascraper = m_starsavn.StarsAVNDataScraper(api_)
        case _:
            pass
    await default(datascraper)
    stop_time = str(int(timeit.default_timer() - archive_time) / 60)[:4]
    print("Archive Completed in " + stop_time + " Minutes")
    return api_
