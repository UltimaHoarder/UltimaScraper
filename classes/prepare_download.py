# Preparing for what?
class start(object):
    def __init__(self, username="", link="", image_url="", post_count=0, webhook=True):
        self.username = username
        self.link = link
        self.image_url = image_url
        self.post_count = post_count
        self.webhook = webhook
        self.user = {}
        self.others = []
