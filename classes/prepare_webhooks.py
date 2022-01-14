from typing import Any


class discord(object):
    def __init__(self):
        self.embeds = []

    class embed(object):
        def __init__(self):
            class image_(object):
                def __init__(self):
                    self.url = ""

            self.title = ""
            self.fields: list[dict[str, Any]] = []
            self.image = image_()

        def add_field(self, name: str, value: str = "", inline: bool = True):
            field: dict[str, Any] = {}
            field["name"] = name
            field["value"] = value
            field["inline"] = inline
            self.fields.append(field)
