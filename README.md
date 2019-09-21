# OnlyFans DataScraper (Python 3.7)
![app-token](Examples/64255399-96a86700-cf21-11e9-8c62-87a483f33701.png)
=============

# Mandatory

From the project folder run this command in your terminal:

`pip install -r requirements.txt`

Open:

`config.json`

Fill in the following:

* `{"app-token":"your_token"}`
* `{"sess":"your_sess"}`
* `{"user-agent":"your_user-agent"}`


Go to www.onlyfans.com and login, open the network debugger, then check the image below on how to get app-token, sess and user-agent

![app-token](examples/1.png)

  
# OPTIONAL

Open:

`config.json`

directory:

    Leave directory empty if you want files to be downloaded in the script folder

    If you're going to fill, please remember to use forward ("/") slashes only

file_name_format:

    {username} = The account's username

    {text} = The post's text

    {date} = The post's date

    {file_name} = The media's file name

    {ext} = The media's file extension

    Example: {date}/{text}-{file_name}.{ext}
    Warning: It's important to keep a unique identifier next to .{ext}. By default it's {file_name}, but it can be {date}-{text}.ext


# OPTIONAL ARGUMENTS

-l

    This will only scrape and export links to a json file without downloading the media types
