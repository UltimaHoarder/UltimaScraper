
from itertools import product
import os
import timeit
from typing import Optional, Union

import helpers.main_helper as main_helper
from helpers.main_helper import choose_option
import modules.bbwchan as m_bbwchan
import modules.fourchan as m_fourchan
import modules.onlyfans as m_onlyfans
from apis.onlyfans import onlyfans as OnlyFans
from apis.starsavn import starsavn as StarsAVN
import modules.patreon as m_patreon
import modules.starsavn as m_starsavn
import time

api_helper = OnlyFans.api_helper

# test_ip = None
# def multi(link,session):
#     global test_ip
#     r = session.get(link)
#     text = r.text.strip('\n')
#     if test_ip == None:
#         test_ip = text
#     return text


def start_datascraper(json_config: dict, site_name_lower: str, api: Optional[OnlyFans.start] = None, webhooks=True):
    json_settings = json_config["settings"]
    json_webhooks = json_settings["webhooks"]
    json_sites = json_config["supported"]
    domain = json_settings["auto_site_choice"]
    main_helper.assign_vars(json_config)

    json_site_settings = json_sites[site_name_lower]["settings"]

    auto_scrape_names = json_site_settings["auto_scrape_names"]
    if isinstance(auto_scrape_names, str):
        temp_identifiers = auto_scrape_names.split(",")
        identifiers = [x for x in temp_identifiers if x]
    else:
        identifiers = []
    auto_profile_choice = json_site_settings["auto_profile_choice"]
    subscription_array = []
    original_sessions = []
    original_sessions = api_helper.create_session(
        settings=json_settings)
    original_sessions = [x for x in original_sessions if x]
    if not original_sessions:
        print("Unable to create session")
        return False
    archive_time = timeit.default_timer()
    if site_name_lower == "onlyfans":
        site_name = "OnlyFans"
        module = m_onlyfans
        if not api:
            api = api if api else OnlyFans.start()
            api = main_helper.process_profiles(
                json_settings, original_sessions, site_name, api)
            print

        subscription_array = []
        auth_count = 0
        jobs = json_site_settings["jobs"]
        subscription_list = module.format_options(
            api.auths, "users")
        if not auto_profile_choice:
            print("Choose Profile")
        auths = choose_option(
            subscription_list, auto_profile_choice)
        api.auths = [x.pop(0) for x in auths]
        for auth in api.auths:
            if not auth.auth_details:
                continue
            dr_link = "https://raw.githubusercontent.com/DATAHOARDERS/dynamic-rules/main/onlyfans.json"
            auth.session_manager.dynamic_rules = auth.session_manager.json_request(dr_link, force_json=True)
            module.assign_vars(auth.auth_details, json_config,
                               json_site_settings, site_name)
            setup = False
            setup, subscriptions = module.account_setup(
                auth, identifiers, jobs, auth_count)
            if not setup:
                if webhooks:
                    x = main_helper.process_webhooks(
                        api, "auth_webhook", "failed")
                auth_details = {}
                auth_details["auth"] = auth.auth_details.__dict__
                profile_directory = auth.profile_directory
                if profile_directory:
                    user_auth_filepath = os.path.join(
                        auth.profile_directory, "auth.json")
                    main_helper.export_data(
                        auth_details, user_auth_filepath)
                continue
            auth_count += 1
            subscription_array += subscriptions
            x = main_helper.process_webhooks(
                api, "auth_webhook", "succeeded")
        subscription_list = module.format_options(
            subscription_array, "usernames")
        if jobs["scrape_paid_content"]:
            print("Scraping Paid Content")
            paid_content = module.paid_content_scraper(api, identifiers)
        if jobs["scrape_names"]:
            print("Scraping Subscriptions")
            names = main_helper.process_names(
                module, subscription_list, auto_scrape_names, api, json_config, site_name_lower, site_name)
        x = main_helper.process_downloads(api, module)
        if webhooks:
            x = main_helper.process_webhooks(
                api, "download_webhook", "succeeded")
    elif site_name_lower == "starsavn":
        pass
        # site_name = "StarsAVN"
        # original_api = StarsAVN
        # module = m_starsavn
        # apis = main_helper.process_profiles(
        #     json_settings, original_sessions, site_name, original_api)
        # auto_profile_choice = json_site_settings["auto_profile_choice"]
        # subscription_array = []
        # auth_count = -1
        # jobs = json_site_settings["jobs"]
        # subscription_list = module.format_options(
        #     apis, "users")
        # apis = choose_option(
        #     subscription_list, auto_profile_choice)
        # apis = [x.pop(0) for x in apis]
        # for api in apis:
        #     module.assign_vars(api.auth.auth_details, json_config,
        #                        json_site_settings, site_name)
        #     identifier = ""
        #     setup = False
        #     setup = module.account_setup(api, identifier=identifier)
        #     if not setup:
        #         auth_details = api.auth.auth_details.__dict__
        #         user_auth_filepath = os.path.join(
        #             api.auth.profile_directory, "auth.json")
        #         main_helper.export_data(
        #             auth_details, user_auth_filepath)
        #         continue
        #     if jobs["scrape_names"]:
        #         array = module.manage_subscriptions(
        #             api, auth_count, identifier=identifier)
        #         subscription_array += array
        # subscription_list = module.format_options(
        #     subscription_array, "usernames")
        # if jobs["scrape_paid_content"]:
        #     print("Scraping Paid Content")
        #     paid_content = module.paid_content_scraper(apis)
        # if jobs["scrape_names"]:
        #     print("Scraping Subscriptions")
        #     names = main_helper.process_names(
        #         module, subscription_list, auto_scrape_names, apis, json_config, site_name_lower, site_name)
        # x = main_helper.process_downloads(apis, module)
    stop_time = str(
        int(timeit.default_timer() - archive_time) / 60)[:4]
    print('Archive Completed in ' + stop_time + ' Minutes')
    return api
