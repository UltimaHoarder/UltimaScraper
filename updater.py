import io
import requests
from zipfile import ZipFile
import os
from pathlib import Path
import shutil
import time

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
with ZipFile(content, "r") as zipObject:
    listOfFileNames = zipObject.namelist()
    root = listOfFileNames[0]
    zipObject.extractall()
    all_files = []
    for root, subdirs, files in os.walk(root):
        x = [os.path.join(root, x) for x in files]
        all_files.extend(x)
    for filepath in all_files:
        filepath = os.path.normpath(filepath)
        parents = Path(filepath).parents
        p = Path(filepath).parts[0]
        renamed = os.path.relpath(filepath, p)
        folder = os.path.dirname(renamed)
        if folder:
            os.makedirs(os.path.dirname(renamed), exist_ok=True)
        q = shutil.move(filepath, renamed)
        print
    print(f"Script has been updated, exiting in 5 seconds")
    time.sleep(5)
