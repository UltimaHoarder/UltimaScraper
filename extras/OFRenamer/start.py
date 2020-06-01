import os
import json
# WORK IN PROGRESS
directory = ""

models = os.listdir(directory)
print(models)
for model in models:
    metadata_directory = os.path.join(directory, model, "Metadata")
    folders = os.listdir(metadata_directory)
    for metadata_file in folders:
        metadata_filepath = os.path.join(metadata_directory, metadata_file)
        metadatas = json.load(open(metadata_filepath))[0]["valid"]
        for metadata in metadatas:
            for folder in metadata:
                model_folder = folder["directory"]
                filename = folder["filename"]
                filepath = os.path.join(model_folder, filename)
                if os.path.isfile(filepath):
                    print
                else:
                    print
