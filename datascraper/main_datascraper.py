import logging
import os
import time
import timeit
import copy
from argparse import ArgumentParser

import helpers.main_helper as main_helper
from helpers.main_helper import module_chooser
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
    global_user_agent = json_settings['global_user_agent']
    domain = json_settings["auto_site_choice"]
    path = os.path.join('.settings', 'extra_auth.json')
    extra_auth_config, extra_auth_config2 = main_helper.get_config(path)
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

            json_auth_array = [json_sites[site_name_lower]
                               ["auth"]]

            json_site_settings = json_sites[site_name_lower]["settings"]
            auto_scrape_names = json_site_settings["auto_scrape_names"]
            extra_auth_settings = json_sites[site_name_lower]["extra_auth_settings"] if "extra_auth_settings" in json_sites[site_name_lower] else {
                "extra_auth": False}
            extra_auth = extra_auth_settings["extra_auth"]
            if extra_auth:
                choose_auth = extra_auth_settings["choose_auth"]
                merge_auth = extra_auth_settings["merge_auth"]
                json_auth_array += extra_auth_config["supported"][site_name_lower]["auths"]
                if choose_auth:
                    json_auth_array = main_helper.choose_auth(json_auth_array)
            apis = []
            module = m_onlyfans
            subscription_array = []
            legacy = True
            original_sessions = api_helper.create_session(
                settings=json_settings)
            if not original_sessions:
                print("Unable to create session")
                continue
            archive_time = timeit.default_timer()
            if site_name_lower == "onlyfans":
                site_name = "OnlyFans"
                subscription_array = []
                auth_count = -1
                for json_auth in json_auth_array:
                    api = OnlyFans.start(
                        original_sessions)
                    auth_count += 1
                    user_agent = global_user_agent if not json_auth[
                        'user_agent'] else json_auth['user_agent']

                    module = m_onlyfans
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
                        pass
                        paid_contents = api.get_paid_content()
                        paid_content = module.paid_content_scraper(api)
                    apis.append(api)
                subscription_list = module.format_options(
                    subscription_array, "usernames")
                x = main_helper.process_names(
                    module, subscription_list, auto_scrape_names, json_auth_array, apis, json_config, site_name_lower, site_name)
                x = main_helper.process_downloads(apis,module)
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
