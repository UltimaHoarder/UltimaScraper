import modules.onlyfans as onlyfans
import timeit
import json
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
    app_token = json_auth['app-token']
    auth_id = json_auth['auth_id']
    auth_hash = json_auth['auth_hash']
    session = ""
    if site_name == "onlyfans":
        x = onlyfans
    elif site_name == "justforfans":
        print("Not Ready Yet")
        continue
        x = onlyfans

    session = x.create_session(user_agent, auth_id, auth_hash, app_token)
    if not session:
        continue
    print('Input a '+site_name+' '+'username or profile link')
    input_link = input().strip()
    username = input_link.rsplit('/', 1)[-1]
    start_time = timeit.default_timer()
    result = x.start_datascraper(session, app_token, username)
    stop_time = str(int(timeit.default_timer() - start_time) / 60)
    print('Task Completed in ' + stop_time + ' Minutes')
