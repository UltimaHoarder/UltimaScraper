class discord(object):
    def __init__(self):
        self.embeds = []

    class embed(object):
        def __init__(self):
            class image(object):
                def __init__(self):
                    self.url = ""
            self.title = ""
            self.fields = []
            self.image = image()

        def add_field(self, name, value="", inline=True):
            field = {}
            field["name"] = name
            field["value"] = value
            field["inline"] = inline
            self.fields.append(field)
