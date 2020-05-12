import os
import json
from itertools import chain
import shutil


def sorter(user_directory, api_type, location, metadata):
    legacy_directory = os.path.join(user_directory, api_type, location)
    if not os.path.isdir(legacy_directory):
        return
    legacy_files = os.listdir(legacy_directory)
    metadata_directory = os.path.join(
        user_directory, "Metadata", api_type+".json")
    results = list(chain(*metadata["valid"]))
    for result in results:
        legacy_filepath = os.path.join(legacy_directory, result["filename"])
        filepath = os.path.join(result["directory"], result["filename"])
        if result["filename"] in legacy_files:
            shutil.move(legacy_filepath, filepath)
    if not os.listdir(legacy_directory):
        os.removedirs(legacy_directory)
