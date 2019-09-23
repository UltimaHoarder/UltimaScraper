# OnlyFans DataScraper (Python 3.7)
![app-token](examples/64255399-96a86700-cf21-11e9-8c62-87a483f33701.png)
=============

# Mandatory

From the project folder run this command in your terminal:

`pip install -r requirements.txt`

Open:

`config.json`

[auth]

Fill in the following:

* `{"app-token":"your_token"}`
* `{"auth_id":"your_auth_id"}`
* `{"auth_hash":"your_auth_hash"}`
* `{"user-agent":"your_user-agent"}`


Go to www.onlyfans.com and login, open the network debugger, then check the image below on how to get app-token, auth_id, auth_hash and user-agent

![app-token](examples/1.png)

  
# OPTIONAL

Open:

`config.json`

[settings]

directory:
    
    Default = ""
    Leave directory empty if you want files to be downloaded in the script folder.

    If you're going to fill, please remember to use forward ("/") slashes only.

file_name_format:

    Default = "{file_name}.{ext}"

    {username} = The account's username

    {text} = The post's text

    {date} = The post's date

    {file_name} = The media's file name

    {ext} = The media's file extension

    Example: {date}/{text}-{file_name}.{ext}
    Warning: It's important to keep a unique identifier next to .{ext}. By default it's {file_name}, but it can be {date}-{text}.ext
    
auto_choice:

    Default = ""

    When you start the script you will be presented with the following scraping choices:
    a = Everything
    b = Images
    c = Videos

    You can automatically choose what you want to scrape if you add it in the config file.

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



# OPTIONAL ARGUMENTS

-l

    This will only scrape and export links to a json file without downloading any files.

# API

You can import the following functions from modules.onlyfans
These functions will go through various changes, so each commit may break your code.

create_session(user_agent, auth_id, auth_hash, app_token)
    
    This function will try to create and return a authenticated session.
    
get_subscriptions(session, app_token)

    This function will return an array of all the accounts you're subscribed too.


start_datascraper(session, app_token, username)

    This function will scrape the username/link you pass.
    The function will return true if scrape finished and false if something went wrong.
