# OnlyFans DataScraper (Python 3.8.X)
![app-token](examples/64255399-96a86700-cf21-11e9-8c62-87a483f33701.png)
=============

# Mandatory

Read the [#FAQ](https://github.com/DIGITALCRIMINAL/OnlyFans/blob/master/README.md#faq) at the bottom of this page before submitting a issue.

From the project folder open CMD/Terminal and run the command below:

`pip install -r requirements.txt`

Open:

`config.json`

[auth]

Fill in the following:

* `{"auth_id":"your_auth_id"}`
* `{"auth_hash":"your_auth_hash"}`
* `{"user-agent":"your_user-agent"}`

Optional change:
* `{"sess":"your_sess_token"}`
* `{"app-token":"your_token"}`


Go to www.onlyfans.com and login, open the network debugger, then check the image below on how to get app-token, auth_id, auth_hash, sess and user-agent

![app-token](examples/1.png)

Your auth config should look similar to this

![app-token](examples/2.png)
# USAGE

`python start_ofd.py`

Enter in inputs as prompted by console.

  
# OPTIONAL

Open:

`config.json` (Open with a texteditor)

[settings]

directory:
    
    Default = ""
    Leave directory empty if you want files to be downloaded in the script folder.

    If you're going to fill, please remember to use forward ("/") slashes only.

file_name_format:

    Default = "{file_name}.{ext}"

    {username} = The account's username

    {date} = The post's date

    {id} = The media's ID (onlyfans-specific)

    {file_name} = The media's file name

    {ext} = The media's file extension

    Example: {date}/{text}-{file_name}.{ext}
    Warning: It's important to keep a unique identifier next to .{ext}. By default it's {file_name}.
    
text_length:

    Default = ""
    Ideal = "50"
    Max = "240"

    When you use {text} in file_name_format, a limit of how many characters can be set by inputting a number.
    
auto_site_choice:

    Default = ""

    When you start the script you will be presented with the following scraping choices:
    onlyfans = onlyfans
    justforfans = justforfans

    You can automatically choose what you want to scrape if you add it in the config file.
    
auto_choice:

    Default = ""

    When you start the script you will be presented with the following scraping choices:
    Everything = "a"
    Images = "b"
    Videos = "c"
    Audios = "d"

    You can automatically choose what you want to scrape if you add it in the config file.
    
auto_scrape_names:

    Default = false

    If set to true, the script will scrape all the names.
    
|**NEW**| [auto_scrape_apis](#auto_scrape_apis):

    Default = true

    If set to false, you'll be given the option to scrape individual apis.
    
export_type:

    Default = "json"

    a = "json"
    b = "csv"

    You can export an archive to different formats.

overwrite_files:

    Default = true

    If set to false, any file with the same name won't be downloaded.

date_format:

    Default = "%d-%m-%Y"

    If you live in the USA and you want to use the incorrect format, use the following:

    "%m-%d-%Y"

multithreading:

    Default = true

    If set to false, you will download files 1 by 1. (If you don't have fast internet, may god help you.)
    I'd reccomend leaving it set to true.

exit_on_completion:

    Default = false

    If set to true the scraper run once and exit upon completion, otherwise the scraper will give the option to run again. This is useful if the scraper is being executed by a cron job or another script.

infinite_loop:

    Default = true

    If set to false, the script will run once and ask you to input anything to continue.

loop_timeout:

    Default = 0

    When infinite_loop is set to true this will set the time in seconds to pause the loop in between runs. 


boards:

    Default = []
    Example = ["s", "gif"]

    Input boards names that you want to automatically scrape.

ignored_keywords:

    Default = []
    Example = ["ignore", "me"]

    Any words you input, the script will ignore any content that contains these words.

ignore_unfollowed_accounts:

    Default = ""
    a = "all"
    b = "paid"
    c = "free"

    This setting will not include any paid or free accounts that you've unfollowed in your subscription list.

    Example: "ignore_unfollowed_accounts": "paid"

    This choice will not include any unfollowed accounts that you've paid for.

|**NEW**| [blacklist_name](#blacklist_name):

    Default = ""

    This setting will not include any blacklisted usernames when you choose the "scrape all" option.

    Go to https://onlyfans.com/my/lists and create a new list; you can name it whatever you want but I called mine "Blacklisted".

    Add the list's name to the config.

    Example: "blacklist_name": "Blacklisted"

    You can create as many lists as you want.
    


|**NEW**| [OPTIONAL ARGUMENTS](#OPTIONAL_ARGUMENTS)

-m

    The script will download metadata files only.

# API

You can import the following functions from modules.onlyfans
These functions will go through various changes, so each commit may break your code.

create_session(user_agent, auth_id, auth_hash, app_token)
    
    This function will try to create and return a authenticated session along with your subscriber count.
    
get_subscriptions(session, app_token, subscriber_count)

    This function will return an array of all the accounts you're subscribed too.


start_datascraper(session, app_token, username)

    This function will scrape the username/link you pass.
    The function will return true if scrape has finished and false if something went wrong.

# FAQ
Before troubleshooting, make sure you're using Python 3.8.

Error: Access Denied /  Auth Loop

    Make sure your cookies and user-agent are correct.

AttributeError: type object 'datetime.datetime' has no attribute 'fromisoformat'

    Only works with Python 3.7 and above.

I'm getting authed into the wrong account

    Enjoy the free content.

I'm using Linux OS and something isn't working.

    Script was built on Windows 10. If you're using Linux you can still submit an issue and I'll try my best to fix it. 
