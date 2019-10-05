import timeit, json
# Open config.json and fill in MANDATORY information for the script to work
json_config = json.load(open('config.json'))

json_authOF = json_config["authOF"]
app_token = json_authOF['app-token']
auth_id = json_authOF['auth_id']
auth_hash = json_authOF['auth_hash']
user_agent = json_authOF['user-agent']

json_authJFF = json_config["authJFF"]
phpsessid = json_authJFF['PHPSESSID']
userhash2 = json_authJFF['UserHash2']
user_agent = json_authJFF['user-agent']

while True:
    print('Input a profile link')
    input_link = input().strip()
    if "?" in input_link:
        input_link = input_link.rsplit("?", 1)[0]
    domain = input_link.rsplit('/', 1)[-2].lower()
    username = input_link.rsplit('/', 1)[-1]
    start_time = timeit.default_timer()
    if "onlyfans" in domain:
        from modules.onlyfans import start_datascraper, create_session, json
        session = create_session(user_agent, auth_id, auth_hash, app_token)
        if not session:
            continue
        result = start_datascraper(session, app_token, username)
        stop_time = str(int(timeit.default_timer() - start_time) / 60)
        print('Task Completed in ' + stop_time + ' Minutes')
    if "justfor" in domain:
        from modules.justfor import start_datascraper, create_session, json
        session = create_session(user_agent, phpsessid, userhash2)
        if not session:
            continue
        result = start_datascraper(session, username)
        stop_time = str(int(timeit.default_timer() - start_time) / 60)
        print('Task Completed in ' + stop_time + ' Minutes')
