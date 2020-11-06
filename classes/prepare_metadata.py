from itertools import groupby, chain
from math import exp


class prepare_metadata(object):
    def __init__(self, metadata={}, export=False, reformat=False, args={}):
        def valid_invalid(valid, invalid, export):
            if all(isinstance(x, list) for x in valid):
                valid = list(chain.from_iterable(valid))
            valid = [self.media(x, export) for x in valid]
            valid = [list(g) for k, g in groupby(
                valid, key=lambda x: x.post_id)]
            invalid = [self.media(x, export) for x in invalid]
            invalid = [list(g) for k, g in groupby(
                invalid, key=lambda x: x.post_id)]
            return valid, invalid

        class assign_state(object):
            def __init__(self, valid, invalid, export) -> None:
                valid, invalid = valid_invalid(valid, invalid, export)
                self.valid = valid
                self.invalid = invalid

        class media_types():
            def __init__(self, option={}) -> None:
                self.Images = option.get("Images")
                self.Videos = option.get("Videos")
                self.Audios = option.get("Audios")
                self.Texts = option.get("Texts")
            def __iter__(self):
                for attr, value in self.__dict__.items():
                    yield attr, value
        collection = media_types()

        if "directories" in metadata:
            metadata.pop("directories")

        for key, item in metadata.items():
            if not item:
                continue
            x = assign_state(**item, export=export)
            setattr(collection, key, x)
        collection = {key:value for key,value in collection if value}
        self.metadata = collection

    class media(object):
        def __init__(self, option={}, export=False, reformat=False):
            self.post_id = option.get("post_id", None)
            self.media_id = option.get("media_id", None)
            self.links = option.get("links", [])
            self.price = option.get("price", None)
            self.text = option.get("text", "")
            self.postedAt = option.get("postedAt", "")
            self.paid = option.get("paid", False)
            self.directory = option.get("directory", "")
            self.filename = option.get("filename", "")
            self.size = option.get("size", None)
            self.session = option.get("session", None)
            self.downloaded = option.get("downloaded", False)
            if export:
                self.prepare_export()
            if reformat:
                print

        def prepare_export(self):
            delattr(self, "session")

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value
