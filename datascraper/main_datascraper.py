
import json
import logging
import os
import time
import timeit
from argparse import ArgumentParser
import copy

import helpers.main_helper as main_helper
from helpers.main_helper import update_config
import modules.bbwchan as bbwchan
import modules.fourchan as fourchan
import modules.onlyfans as onlyfans
import modules.starsavn as starsavn
import classes.make_config as make_config


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
    # Open config.json and fill in MANDATORY information for the script to work
    path = os.path.join('.settings', 'config.json')
    if os.path.isfile(path):
        json_config = json.load(open(path))
    else:
        json_config = {}
    json_config2 = json.loads(json.dumps(make_config.start(
        **json_config), default=lambda o: o.__dict__))
    if json_config != json_config2:
        update_config(json_config2)
    if not json_config:
        input("The .settings\\config.json file has been created. Fill in whatever you need to fill in and then press enter when done.\n")
        json_config2 = json.load(open(path))
    json_config = copy.deepcopy(json_config2)
    json_settings = json_config["settings"]
    json_sites = json_config["supported"]
    infinite_loop = json_settings["infinite_loop"]
    global_user_agent = json_settings['global_user_agent']
    domain = json_settings["auto_site_choice"]
    path = os.path.join('.settings', 'extra_auth.json')
    extra_auth_config = json.load(open(path))
    exit_on_completion = json_settings['exit_on_completion']
    loop_timeout = json_settings['loop_timeout']

    string = ""
    site_names = []
    if not domain:
        site_count = len(json_sites)
        count = 0
        for x in json_sites:
            string += str(count)+" = "+x
            site_names.append(x)
            if count+1 != site_count:
                string += " | "

            count += 1
    try:
        while True:
            if domain:
                site_name = domain
            else:
                print("Site: "+string)
                x = int(input())
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
                x.assign_vars(json_config, json_site_settings)
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
                    cookies = session["session"].cookies.get_dict()
                    json_auth['auth_id'] = cookies["auth_id"]
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
            elif site_name_lower == "starsavn":
                legacy = False
                site_name = "StarsAVN"
                subscription_array = []
                auth_count = -1
                x = starsavn
                x.assign_vars(json_config, json_site_settings)
                for json_auth in json_auth_array:
                    auth_count += 1
                    user_agent = global_user_agent if not json_auth[
                        'user_agent'] else json_auth['user_agent']
                    sess = json_auth['sess']

                    auth_array = dict()
                    auth_array["sess"] = sess
                    session = x.create_session(
                        user_agent, app_token, auth_array)
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
                x.assign_vars(json_config, json_site_settings)
                session_array = [x.create_session()]
                array = x.get_subscriptions()
                subscription_array = x.format_options(array)
            elif site_name == "bbwchan":
                x = bbwchan
                site_name = "BBWChan"
                x.assign_vars(json_config, json_site_settings)
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
                    name = name[1]
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
