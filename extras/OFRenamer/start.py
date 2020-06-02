import os
import json
import sys
sys.path.append('.')
import helpers.main_helper as main_helper
# WORK IN PROGRESS
directory = ""
config = ""
json_config = json.load(open(config))["supported"]["onlyfans"]
json_settings = json_config["settings"]
models_folder = os.listdir(directory)
print(models_folder)
for model_folder in models_folder:
    username = model_folder
    metadata_directory = os.path.join(directory, model_folder, "Metadata")
    folders = os.listdir(metadata_directory)
    for metadata_file in folders:
        metadata_filepath = os.path.join(metadata_directory, metadata_file)
        metadatas = json.load(open(metadata_filepath))[0]["valid"]
        for metadata in metadatas:
            for model in metadata:
                model_folder = model["directory"]
                filename = model["filename"]
                post_id = str(model["post_id"])
                filepath = os.path.join(model_folder, filename)
                class prepare_reformat(object):
                    def __init__(self, option):
                        self.directory = option.get('directory', "")
                        self.post_id = option.get('post_id', "")
                        self.media_id = option.get('media_id', "")
                        filename, ext = os.path.splitext(filepath)
                        self.filename = option.get('filename', "")
                        self.username = option.get('username', username)
                        self.text = option.get('text', "")
                        self.postedAt = option.get('postedAt', "")
                        print
                x = prepare_reformat(model)
                x = json.loads(json.dumps(x, default=lambda o: o.__dict__))
                if os.path.isfile(filepath):
                    new_format = main_helper.reformat(*x)
                    print
                else:
                    print
