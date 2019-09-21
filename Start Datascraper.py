from modules.onlyfans import start_datascraper, json
# Open config.json and fill in MANDATORY information for the script to work
json_config = json.load(open('config.json'))

json_auth = json_config["auth"]
app_token = json_auth['app-token']
sess = json_auth['sess']
user_agent = json_auth['user-agent']

while True:
    print('Input a username or profile link')
    input_link = input().strip()
    username = input_link.rsplit('/', 1)[-1]
    result = start_datascraper(app_token, user_agent, sess, username)
