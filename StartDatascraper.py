import modules.onlyfans as onlyfans
import modules.justforfans as justforfans
import modules.four_chan as four_chan
import modules.bbwchan as bbwchan
import modules.helpers as helpers
import timeit
import json
import logging
import traceback
import inspect
import os

# Configure logging to the console and file system at INFO level and above
logging.basicConfig(handlers=[logging.FileHandler('application.log', 'w', 'utf-8')], level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
console.setFormatter(formatter)
logging.getLogger("").addHandler(console)

# Open config.json and fill in MANDATORY information for the script to work
path = os.path.join('settings', 'config.json')
json_config = json.load(open(path))
json_sites = json_config["supported"]
json_settings = json_config["settings"]
infinite_loop = json_settings['infinite_loop']
global_user_agent = json_settings['global_user-agent']
domain = json_settings["auto_site_choice"]
path = os.path.join('settings', 'extra_auth.json')
extra_auth_config = json.load(open(path))

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
        auto_scrape_all = json_site_settings["auto_scrape_all"]
        extra_auth_settings = json_sites[site_name_lower]["extra_auth_settings"] if "extra_auth_settings" in json_sites[site_name_lower] else {
            "extra_auth": False}
        extra_auth = extra_auth_settings["extra_auth"]
        choose_auth = extra_auth_settings["choose_auth"]
        merge_auth = extra_auth_settings["merge_auth"]
        if extra_auth:
            json_auth_array += extra_auth_config[site_name_lower]["extra_auth"]
            if choose_auth:
                json_auth_array = helpers.choose_auth(json_auth_array)
        session_array = []
        x = onlyfans
        app_token = ""
        subscription_array = []
        legacy = True
        if site_name_lower == "onlyfans":
            legacy = False
            subscription_array = []
            auth_count = -1
            for json_auth in json_auth_array:
                auth_count += 1
                app_token = json_auth['app-token']
                user_agent = global_user_agent if not json_auth['user-agent'] else json_auth['user-agent']

                auth_id = json_auth['auth_id']
                auth_hash = json_auth['auth_hash']
                sess = json_auth['sess']

                auth_array = dict()
                auth_array["auth_id"] = auth_id
                auth_array["auth_hash"] = auth_hash
                auth_array["sess"] = sess
                x = onlyfans
                session = x.create_session(
                    user_agent, app_token, auth_array)
                session_array.append(session)
                if not session[0]:
                    continue
                me_api = session[3]
                array = x.get_subscriptions(
                    session[0], app_token, session[2], me_api, auth_count)
                subscription_array += array
            subscription_array = x.format_options(subscription_array)
        elif site_name == "justforfans":
            for json_auth in json_auth_array:
                auth_id = json_auth['phpsessid']
                auth_hash = json_auth['user_hash2']
                user_agent = global_user_agent if not json_auth['user-agent'] else json_auth['user-agent']
                x = justforfans
                session_array = [x.create_session(
                    user_agent, auth_id, auth_hash)]
                array = x.get_subscriptions()
        elif site_name == "4chan":
            x = four_chan
            session_array = [x.create_session()]
            array = x.get_subscriptions()
            subscription_array = x.format_options(array)
        elif site_name == "bbwchan":
            x = bbwchan
            session_array = [x.create_session()]
            array = x.get_subscriptions()
            subscription_array = x.format_options(array)
        names = subscription_array[0]
        if names:
            print("Names: "+subscription_array[1])
            if not auto_scrape_all:
                value = int(input().strip())
            else:
                value = 0
            if value:
                names = [names[value]]
            else:
                names.pop(0)
        else:
            print("You're not subscribed to any users.")
            continue
        start_time = timeit.default_timer()
        download_list = []
        for name in names:
            if not legacy:
                json_auth = json_auth_array[name[0]]
                auth_count = name[0]
                session = session_array[auth_count][0]
                name = name[1]
            else:
                session = session_array[0][0]
            username = helpers.parse_links(site_name_lower, name)
            result = x.start_datascraper(
                session, username, site_name, app_token)
            download_list.append(result)
        for y in download_list:
            for arg in y[1]:
                x.download_media(*arg)
        stop_time = str(int(timeit.default_timer() - start_time) / 60)
        print('Task Completed in ' + stop_time + ' Minutes')
        if not infinite_loop:
            print("Input anything to continue")
            input()
except Exception as e:
    tb = traceback.format_exc()
    print(tb+"\n")
    v1 = inspect.trace()[-1][0].f_locals
    # print(v1)
    if "s" in v1:
        print(v1["s"])
    input()
