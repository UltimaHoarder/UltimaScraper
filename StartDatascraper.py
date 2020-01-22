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

# Configure logging to the console and file system at INFO level and above
logging.basicConfig(handlers=[logging.FileHandler('application.log', 'w', 'utf-8')], level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
console.setFormatter(formatter)
logging.getLogger("").addHandler(console)

# Open config.json and fill in MANDATORY information for the script to work
json_config = json.load(open('config.json'))
json_sites = json_config["supported"]
json_settings = json_config["settings"]
infinite_loop = json_settings['infinite_loop']
user_agent = json_settings['user-agent']
domain = json_settings["auto_site_choice"]

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
        json_auth = json_sites[site_name_lower]["auth"]
        json_site_settings = json_sites[site_name_lower]["settings"]
        auto_scrape_all = json_site_settings["auto_scrape_all"]
        session = []
        x = onlyfans
        app_token = ""
        array = []
        if site_name_lower == "onlyfans":
            app_token = json_auth['app-token']
            sess = json_auth['sess'] if json_auth['sess'] else "None"
            x = onlyfans
            session = x.create_session(
                user_agent, app_token, sess)
            if not session[0]:
                continue
            me_api = session[3]
            array = x.get_subscriptions(session[0], app_token, session[2])
            if me_api["isPerformer"]:
                array = [{"username": me_api["username"]}] + array
            array = x.format_options(array)
        elif site_name == "justforfans":
            auth_id = json_auth['phpsessid']
            auth_hash = json_auth['user_hash2']
            x = justforfans
            session = x.create_session(user_agent, auth_id, auth_hash)
            array = x.get_subscriptions()
        elif site_name == "4chan":
            x = four_chan
            session = x.create_session()
            array = x.get_subscriptions()
            array = x.format_options(array)
        elif site_name == "bbwchan":
            x = bbwchan
            session = x.create_session()
            array = x.get_subscriptions()
            array = x.format_options(array)
        names = array[0]
        if names:
            print("Names: "+array[1])
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
            username = helpers.parse_links(site_name_lower, name)
            result = x.start_datascraper(
                session[0], username, site_name, app_token)
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
