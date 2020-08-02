
import json
import logging
import os
import time
import timeit
from argparse import ArgumentParser

import helpers.main_helper as main_helper
from helpers.main_helper import update_config
import modules.bbwchan as bbwchan
import modules.fourchan as fourchan
import modules.onlyfans as onlyfans
import modules.patreon as patreon
import modules.starsavn as starsavn


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
    extra_auth_config = json.load(open(path))
    exit_on_completion = json_settings['exit_on_completion']
    loop_timeout = json_settings['loop_timeout']

    string = "Site: "
    site_names = []
    bl = ["patreon"]
    if not domain:
        site_count = len(json_sites)
        count = 0
        for x in json_sites:
            if x in bl:
                continue
            string += str(count)+" = "+x
            site_names.append(x)
            if count+1 != site_count:
                string += " | "

            count += 1
        string += "x = Exit"

    try:
        while True:
            if domain:
                site_name = domain
            else:
                print(string)
                x = input()
                if x is "x":
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
                json_auth_array += extra_auth_config[site_name_lower]["extra_auth"]
                if choose_auth:
                    json_auth_array = main_helper.choose_auth(json_auth_array)
            session_array = []
            x = onlyfans
            app_token = ""
            subscription_array = []
            legacy = True
            if site_name_lower == "onlyfans":
                legacy = False
                site_name = "OnlyFans"
                subscription_array = []
                auth_count = -1
                x.assign_vars(json_config, json_site_settings, site_name)
                for json_auth in json_auth_array:
                    auth_count += 1
                    app_token = json_auth['app_token']
                    user_agent = global_user_agent if not json_auth[
                        'user_agent'] else json_auth['user_agent']

                    x = onlyfans
                    session = x.create_session()
                    session = x.create_auth(session,
                                            user_agent, app_token, json_auth)
                    session_array.append(session)
                    if not session["session"]:
                        continue
                    # x.get_paid_posts(session["session"],app_token)
                    cookies = session["session"].cookies.get_dict()
                    auth_id = cookies["auth_id"]
                    json_auth['auth_id'] = auth_id
                    json_auth['auth_uniq_'] = cookies["auth_uniq_"+auth_id]
                    json_auth['auth_hash'] = cookies["auth_hash"]
                    json_auth['sess'] = cookies["sess"]
                    json_auth['fp'] = cookies["fp"]
                    if json_config != json_config2:
                        update_config(json_config)
                    me_api = session["me_api"]
                    array = x.get_subscriptions(
                        session["session"], app_token, session["subscriber_count"], me_api, auth_count)
                    subscription_array += array
                subscription_array = x.format_options(
                    subscription_array, "usernames")
            if site_name_lower == "patreon":
                legacy = False
                site_name = "Patreon"
                subscription_array = []
                auth_count = -1
                x = patreon
                x.assign_vars(json_config, json_site_settings, site_name)
                for json_auth in json_auth_array:
                    auth_count += 1
                    user_agent = global_user_agent if not json_auth[
                        'user_agent'] else json_auth['user_agent']

                    session = x.create_session()
                    session = x.create_auth(session,
                                            user_agent, json_auth)
                    session_array.append(session)
                    if not session["session"]:
                        continue
                    cookies = session["session"].cookies.get_dict()
                    json_auth['session_id'] = cookies["session_id"]
                    if json_config != json_config2:
                        update_config(json_config)
                    me_api = session["me_api"]
                    array = x.get_subscriptions(
                        session["session"], auth_count)
                    subscription_array += array
                subscription_array = x.format_options(
                    subscription_array, "usernames")
                print
            elif site_name_lower == "starsavn":
                legacy = False
                site_name = "StarsAVN"
                subscription_array = []
                auth_count = -1
                x = starsavn
                x.assign_vars(json_config, json_site_settings, site_name)
                for json_auth in json_auth_array:
                    auth_count += 1
                    user_agent = global_user_agent if not json_auth[
                        'user_agent'] else json_auth['user_agent']
                    sess = json_auth['sess']

                    auth_array = dict()
                    auth_array["sess"] = sess
                    session = x.create_session()
                    session = x.create_auth(session,
                                            user_agent, app_token, json_auth)
                    session_array.append(session)
                    if not session["session"]:
                        continue
                    me_api = session["me_api"]
                    array = x.get_subscriptions(
                        session["session"], app_token, session["subscriber_count"], me_api, auth_count)
                    subscription_array += array
                subscription_array = x.format_options(
                    subscription_array, "usernames")
            elif site_name == "fourchan":
                x = fourchan
                site_name = "4Chan"
                x.assign_vars(json_config, json_site_settings, site_name)
                session_array = [x.create_session()]
                array = x.get_subscriptions()
                subscription_array = x.format_options(array)
            elif site_name == "bbwchan":
                x = bbwchan
                site_name = "BBWChan"
                x.assign_vars(json_config, json_site_settings, site_name)
                session_array = [x.create_session()]
                array = x.get_subscriptions()
                subscription_array = x.format_options(array)
            names = subscription_array[0]
            if names:
                print("Names: "+subscription_array[1])
                if not auto_scrape_names:
                    value = int(input().strip())
                else:
                    value = 0
                if value:
                    names = [names[value]]
                else:
                    names.pop(0)
            else:
                print("There's nothing to scrape.")
                continue
            start_time = timeit.default_timer()
            download_list = []
            for name in names:
                # Extra Auth Support
                if not legacy:
                    json_auth = json_auth_array[name[0]]
                    auth_count = name[0]
                    session = session_array[auth_count]["session"]
                    name = name[-1]
                else:
                    session = session_array[0]["session"]
                main_helper.assign_vars(json_config)
                username = main_helper.parse_links(site_name_lower, name)
                result = x.start_datascraper(
                    session, username, site_name, app_token, choice_type=value)
                if not args.metadata:
                    download_list.append(result)
            for y in download_list:
                for arg in y[1]:
                    x.download_media(*arg)
            stop_time = str(int(timeit.default_timer() - start_time) / 60)
            print('Task Completed in ' + stop_time + ' Minutes')
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
