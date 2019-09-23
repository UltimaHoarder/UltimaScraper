from modules.onlyfans import start_datascraper, create_session, json
import timeit
# Open config.json and fill in MANDATORY information for the script to work
json_config = json.load(open('config.json'))

json_auth = json_config["auth"]
app_token = json_auth['app-token']
auth_id = json_auth['auth_id']
auth_hash = json_auth['auth_hash']
user_agent = json_auth['user-agent']

while True:
    session = create_session(user_agent, auth_id, auth_hash, app_token)
    if not session:
        continue
    print('Input a username or profile link')
    input_link = input().strip()
    username = input_link.rsplit('/', 1)[-1]
    start_time = timeit.default_timer()
    result = start_datascraper(session, app_token, username)
    stop_time = str(int(timeit.default_timer() - start_time) / 60)
    print('Task Completed in ' + stop_time + ' Minutes')
