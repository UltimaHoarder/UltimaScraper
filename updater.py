import io
import os
import subprocess
import time
from pathlib import Path
from zipfile import ZipFile

import requests

# API request limit is around 30, so it fails
# local_commit = "2ca95beec5dd526b9b825497dc6227aafbaf67ad"
# response = requests.get("https://api.github.com/repos/digitalcriminal/onlyfans/branches/master")
# response_json = response.json()
# commit_id = response_json["commit"]["sha"]
# downloaded = requests.get(f"https://github.com/DIGITALCRIMINAL/OnlyFans/archive/{commit_id}.zip")
downloaded = requests.get(
    f"https://github.com/DIGITALCRIMINALS/OnlyFans/archive/refs/heads/master.zip"
)
content = io.BytesIO(downloaded.content)
# Zip download for manual extraction
# download_path = "OnlyFans DataScraper.zip"
# with open(download_path, "wb") as f:
#     f.write(downloaded.content)
def rm_tree(pth: Path):
    for child in pth.iterdir():
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


# We can use GitPython in the future to update?
# This would ensure there's no legacy files and folders left over. We'd also avoid the chicken and the egg problem with updater.py.
with ZipFile(content, "r") as zipObject:
    listOfFileNames = zipObject.namelist()
    root_directory = Path(listOfFileNames[0])
    zipObject.extractall()
    all_files: list[Path] = []
    for root, subdirs, files in os.walk(root_directory):
        x = [Path(root, x) for x in files]
        all_files.extend(x)
    for filepath in all_files:
        update_path = Path(*filepath.parts[1:])
        parent_folder = update_path.parent
        if parent_folder:
            parent_folder.mkdir(parents=True, exist_ok=True)
        q = filepath.replace(update_path)
    rm_tree(root_directory)
    subprocess.run(["poetry", "update"])
    print(f"Script has been updated, exiting in 5 seconds")
    time.sleep(5)
