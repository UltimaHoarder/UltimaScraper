import filecmp
import os
import shutil
from itertools import chain


def sorter(user_directory, api_type, location, metadata):
    legacy_directory = os.path.join(user_directory, api_type, location)
    if not os.path.isdir(legacy_directory):
        return
    legacy_files = os.listdir(legacy_directory)
    results = list(chain(*metadata["valid"]))
    for result in results:
        legacy_filepath = os.path.join(legacy_directory, result["filename"])
        filepath = os.path.join(result["directory"], result["filename"])
        if result["filename"] in legacy_files:
            if os.path.isfile(filepath):
                same_file = filecmp.cmp(
                    legacy_filepath, filepath, shallow=False)
                if same_file:
                    os.remove(filepath)
                else:
                    os.remove(legacy_filepath)
                    continue
            shutil.move(legacy_filepath, filepath)
    if not os.listdir(legacy_directory):
        os.removedirs(legacy_directory)
