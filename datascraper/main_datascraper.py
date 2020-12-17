import logging
import os
import time
import timeit
import copy
from argparse import ArgumentParser

import ujson

import helpers.main_helper as main_helper
from helpers.main_helper import choose_option, module_chooser
import modules.bbwchan as m_bbwchan
import modules.fourchan as m_fourchan
import modules.onlyfans as m_onlyfans
from apis.onlyfans import onlyfans as OnlyFans
from apis.starsavn import starsavn as StarsAVN
import modules.patreon as m_patreon
import modules.starsavn as m_starsavn

api_helper = OnlyFans.api_helper


def start_datascraper():
    parser = ArgumentParser()
    parser.add_argument("-m", "--metadata", action='store_true',
                        help="only exports metadata")
    args = parser.parse_args()
    if args.metadata:
        print("Exporting Metadata Only")
    log_error = main_helper.setup_logger('errors', 'errors.log')
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger("").addHandler(console)
    # root = os.getcwd()
    config_path = os.path.join('.settings', 'config.json')
    json_config, json_config2 = main_helper.get_config(config_path)
    json_settings = json_config["settings"]
    json_sites = json_config["supported"]
    infinite_loop = json_settings["infinite_loop"]
    domain = json_settings["auto_site_choice"]
    path = os.path.join('.settings', 'extra_auth.json')
    # extra_auth_config, extra_auth_config2 = main_helper.get_config(path)
    extra_auth_config = {}
    exit_on_completion = json_settings['exit_on_completion']
    loop_timeout = json_settings['loop_timeout']
    main_helper.assign_vars(json_config)

    string, site_names = module_chooser(domain, json_sites)
    try:
        while True:
            if domain:
                if site_names:
                    site_name = domain
                else:
                    print(string)
                    continue
            else:
                print(string)
                x = input()
                if x == "x":
                    break
                x = int(x)
                site_name = site_names[x]
            site_name_lower = site_name.lower()

            json_site_settings = json_sites[site_name_lower]["settings"]

            auto_scrape_names = json_site_settings["auto_scrape_names"]
            apis = []
            module = m_onlyfans
            subscription_array = []
            original_sessions = []
            original_sessions = api_helper.create_session(
                settings=json_settings)
            original_sessions = [x for x in original_sessions]
            if not original_sessions:
                print("Unable to create session")
                continue
            archive_time = timeit.default_timer()
            if site_name_lower == "onlyfans":
                site_name = "OnlyFans"
                profile_directories = json_settings["profile_directories"]
                auto_profile_choice = json_site_settings["auto_profile_choice"]
                profile_directories2 = []
                for profile_directory in profile_directories:
                    sessions = copy.deepcopy(original_sessions)
                    x = os.path.join(profile_directory, site_name)
                    x = os.path.abspath(x)
                    temp_users = os.listdir(x)
                    for user in temp_users:
                        user_profile = os.path.join(x, user)
                        user_auth_filepath = os.path.join(
                            user_profile, "auth.json")
                        temp_json_auth = {}
                        if os.path.exists(user_auth_filepath):
                            temp_json_auth = ujson.load(
                                open(user_auth_filepath))
                            json_auth = temp_json_auth["auth"]
                            if not json_auth.get("active", None):
                                continue
                            json_auth["username"] = user
                            api = OnlyFans.start(
                                sessions)
                            api.auth.profile_directory = user_profile
                            api.set_auth_details(
                                json_auth)
                            apis.append(api)
                        if temp_json_auth:
                            main_helper.export_json(
                                user_auth_filepath, temp_json_auth)
                            print
                        print
                    print
                    profile_directories2.append(x)
                subscription_array = []
                auth_count = -1
                jobs = json_site_settings["jobs"]
                subscription_list = module.format_options(
                    apis, "users")
                apis = choose_option(
                    subscription_list, auto_profile_choice)
                apis = [x.pop(0) for x in apis]
                print
                for api in apis:
                    module = m_onlyfans
                    module.assign_vars(api.auth.auth_details, json_config,
                                       json_site_settings, site_name)
                    identifier = ""
                    setup = False
                    setup = module.account_setup(api, identifier=identifier)
                    if not setup:
                        api.auth_details.active = False
                        auth_details = api.auth_details.__dict__
                        user_auth_filepath = os.path.join(
                            api.auth.profile_directory, "auth.json")
                        main_helper.export_json(
                            user_auth_filepath, auth_details)
                        continue
                    if jobs["scrape_names"]:
                        array = module.manage_subscriptions(
                            api, auth_count, identifier=identifier)
                        subscription_array += array
                subscription_list = module.format_options(
                    subscription_array, "usernames")
                if jobs["scrape_paid_content"]:
                    print("Scraping Paid Content")
                    paid_content = module.paid_content_scraper(apis)
                if jobs["scrape_names"]:
                    print("Scraping Subscriptions")
                    x = main_helper.process_names(
                        module, subscription_list, auto_scrape_names, apis, json_config, site_name_lower, site_name)
                x = main_helper.process_downloads(apis, module)
                print
            elif site_name_lower == "starsavn":
                site_name = "StarsAVN"
                subscription_array = []
                auth_count = -1
                for json_auth in json_auth_array:
                    sessions = api_helper.copy_sessions(original_sessions)
                    api = StarsAVN.start(
                        sessions)
                    auth_count += 1
                    user_agent = global_user_agent if not json_auth[
                        'user_agent'] else json_auth['user_agent']

                    module = m_starsavn
                    module.assign_vars(json_auth, json_config,
                                       json_site_settings, site_name)
                    api.set_auth_details(
                        **json_auth, global_user_agent=user_agent)
                    setup = module.account_setup(api)
                    if not setup:
                        continue
                    jobs = json_site_settings["jobs"]
                    if jobs["scrape_names"]:
                        array = module.manage_subscriptions(api, auth_count)
                        subscription_array += array
                    if jobs["scrape_paid_content"]:
                        paid_contents = api.get_paid_content()
                        paid_content = module.paid_content_scraper(api)
                    apis.append(api)
                subscription_array = module.format_options(
                    subscription_array, "usernames")
            stop_time = str(
                int(timeit.default_timer() - archive_time) / 60)[:4]
            print('Archive Completed in ' + stop_time + ' Minutes')
            if exit_on_completion:
                print("Now exiting.")
                exit(0)
            elif not infinite_loop:
                print("Input anything to continue")
                input()
            elif loop_timeout:
                print('Pausing scraper for ' + loop_timeout + ' seconds.')
                time.sleep(int(loop_timeout))
    except Exception as e:
        log_error.exception(e)
        input()
