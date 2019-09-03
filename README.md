OnlyFans DataScraper (Python 3.7)
=============

# Mandatory

From the project folder run this command in your terminal:

`pip install -r requirements.txt`

Open:

`settings.json`

Fill in the following:

* `{"app-token":"your_token"}`
* `{"sess":"your_sess"}`
* `{"user-agent":"your_user-agent"}`


Go to www.onlyfans.com and login, open the network debugger, then check the image below on how to get app-token, sess and user-agent

![app-token](Examples/1.png)

  
# OPTIONAL

Open:

`settings.json`

Directory:

`Leave directory empty if you want files to be downloaded in the script folder`

`If you're going to fill, please remember to use forward ("/") slashes only`

# OPTIONAL ARGUMENTS

-l 

`This will only scrape and export links to a json file without downloading the media types`
