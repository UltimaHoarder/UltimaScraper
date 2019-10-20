import os
import modules.onlyfans as onlyfans
import modules.justforfans as justforfans
import modules.four_chan as four_chan
import timeit
import json
import modules.helpers as helpers
# Open config.json and fill in MANDATORY information for the script to work
json_config = json.load(open('config.json'))
json_sites = json_config["supported"]
json_settings = json_config["settings"]
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

while True:

    if domain:
        site_name = domain
    else:
        print("Site: "+string)
        x = int(input())
        site_name = site_names[x]
    json_auth = json_sites[site_name]["auth"]
    json_site_settings = json_sites[site_name]["settings"]
    session = ""
    x = ""
    app_token = ""
    if site_name == "onlyfans":
        app_token = json_auth['app-token']
        auth_id = json_auth['auth_id']
        auth_hash = json_auth['auth_hash']
        x = onlyfans
        session = x.create_session(user_agent, auth_id, auth_hash, app_token)
        array = []
    elif site_name == "justforfans":
        auth_id = json_auth['phpsessid']
        auth_hash = json_auth['user_hash2']
        x = justforfans
        session = x.create_session(user_agent, auth_id, auth_hash)
        array = []
    elif site_name == "4chan":
        x = four_chan
        session = x.create_session()
        array = json_site_settings["boards"]

    if not session[0]:
        continue
    print('Input a '+site_name+' '+session[1])
    session = session[0]
    if not array:
        array = [input().strip()]
    for input_link in array:
        username = helpers.parse_links(site_name, input_link)
        start_time = timeit.default_timer()
        result = x.start_datascraper(session, username, site_name, app_token)
        stop_time = str(int(timeit.default_timer() - start_time) / 60)
        print('Task Completed in ' + stop_time + ' Minutes')
