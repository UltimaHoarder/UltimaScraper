from itertools import groupby


def valid_invalid(item):
    print

    def sort_item(item):
        class Item():
            def __init__(self, option={}):
                self.post_id = option.get("post_id", None)
                self.links = option.get("links", [])
                self.price = option.get("price", None)
                self.text = option.get("text", "")
                self.postedAt = option.get("postedAt", "")
                self.paid = option.get("paid", False)
                self.directory = option.get("directory", "")
                self.filename = option.get("filename", "")
                self.size = option.get("size", None)
                print

        def fix(item):
            return item
        item = fix(item)
        x = Item(item)
        return x

    class sort():
        def __init__(self, valid):
            x = []
            for items in valid:
                if isinstance(items, dict):
                    items = [items]
                    print
                for item in items:
                    x.append(sort_item(item))

            x = [list(g) for k, g in groupby(
                x, key=lambda x: x.post_id)]
            self.sorted = x
    x = sort(item).sorted
    print
    return x


class prepare_metadata(object):
    def update_file(self):
        x = valid_invalid([[self]])
        return x[0][0]

    def __init__(self, items=[]):
        class Item(object):
            def __init__(self, type, valid, invalid):
                print
                self.type = type
                self.valid = valid_invalid(valid)
                self.invalid = valid_invalid(invalid)
                print
        x = []
        for item in items:
            x.append(Item(**item))
        self.items = x


class prepare_reformat(object):
    def __init__(self, directory="", post_id="", media_id="", filename="", text="", ext="", date="", username="", format_path="", date_format="", maximum_length=255):
        self.directory = directory
        self.post_id = post_id
        self.media_id = media_id
        self.filename = filename
        self.text = text
        self.ext = ext
        self.date = date
        self.username = username
        self.format_path = format_path
        self.date_format = date_format
        self.maximum_length = int(maximum_length)

class obj(object):
    def __init__(self, d):
        for a, b in d.items():
            if isinstance(b, (list, tuple)):
               setattr(self, a, [obj(x) if isinstance(x, dict) else x for x in b])
            else:
               setattr(self, a, obj(b) if isinstance(b, dict) else b)