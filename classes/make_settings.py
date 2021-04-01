from apis.onlyfans.onlyfans import auth_details
import os

import ujson
from classes.prepare_metadata import format_types
import uuid as uuid


def export_json(path, metadata):
    if "auth" not in metadata:
        auth = {}
        auth["auth"] = metadata
        metadata = auth
    with open(path, 'w', encoding='utf-8') as outfile:
        ujson.dump(metadata, outfile, indent=2)


def fix(config={}):
    added = []
    changed = []
    fix = []
    settings = {}
    global_user_agent = ""
    for key, value in config.items():
        if key == "settings":
            settings = value
            auto_profile_choice = settings.pop("auto_profile_choice", None)
            socks5_proxies = settings.pop(
                "socks5_proxy", None)
            if socks5_proxies:
                fixed_socks5_proxies = []
                for socks5_proxy in socks5_proxies:
                    fixed_socks5_proxy = f"socks5h://{socks5_proxy}"
                    fixed_socks5_proxies.append(fixed_socks5_proxy)
                settings["proxies"] = fixed_socks5_proxies
            global_user_agent = settings.pop(
                "global_user_agent", None)
            if isinstance(settings.get(
                    "webhooks", {}), list):
                webhook = settings["webhooks"]
                settings["webhooks"] = {}
                settings["webhooks"]["global_webhooks"] = webhook
        if key == "supported":
            for key2, value2 in value.items():
                temp_auth = value2.pop("auth", None)
                if temp_auth:
                    q = os.path.abspath(".settings")
                    backup_config_filepath = os.path.join(
                        q, "config_backup.json")
                    print(
                        f"LEGACY CONFIG FOUND, BACKING IT UP AND CREATING A NEW ONE. ({backup_config_filepath})")
                    export_json(backup_config_filepath, config)
                    print
                    temp_auth["user_agent"] = global_user_agent
                    auth = {}
                    temp_auth = auth_details(temp_auth).__dict__
                    auth["auth"] = temp_auth
                    if "profile_directories" in settings:
                        dpd = settings["profile_directories"][0]
                        default_profile_directory = os.path.join(
                            os.path.abspath(dpd), key2, "default")
                        os.makedirs(default_profile_directory, exist_ok=True)
                        profile_auth_filepath = os.path.join(
                            default_profile_directory, "auth.json")
                        export_json(profile_auth_filepath, auth)
                        print(
                            f"{profile_auth_filepath} HAS BEEN CREATED, CHECK IF IT'S CORRECT.")
                print
                for key3, settings in value2.items():
                    if key3 == "settings":
                        settings["text_length"] = int(settings["text_length"])
                        re = settings.pop("download_paths", None)
                        if re:
                            settings["download_directories"] = re
                            string = f"download_paths to download_directories in {key2}"
                            changed.append(string)
                        re = settings.get("metadata_directory_format", None)
                        if not re:
                            settings["metadata_directory_format"] = "{site_name}/{username}/Metadata"
                            string = f"metadata_directory_format in {key2}"
                            added.append(string)
                        delete_legacy_metadata = settings.get(
                            "delete_legacy_metadata", None)
                        if delete_legacy_metadata == None:
                            message_string = f"{key2} - IN THIS COMMIT I CHANGED HOW STORING METADATA WORKS. 'METADATA_DIRECTORIES' (config.json) NOW CONTROLS WHERE METADATA IS STORED SO MAKE SURE IT'S THE CORRECT DIRECTORY TO AVOID DOWNLOADING DUPES.\nPRESS ENTER TO CONTINUE"
                            print(message_string)
                        filename_format = settings.pop(
                            "file_name_format", None)
                        if filename_format:
                            settings["filename_format"] = filename_format
                        reformats = {k: v for k,
                                     v in settings.items() if "_format" in k}
                        bl = ["date_format"]
                        reformats = {k: v for k,
                                     v in reformats.items() if k not in bl}
                        for re_name, re_value in reformats.items():
                            top = ["{id}", "{file_name}"]
                            bottom = ["{media_id}", "{filename}"]
                            z = list(zip(top, bottom))
                            for x in z:
                                if x[0] in re_value:
                                    settings[re_name] = settings[re_name].replace(
                                        x[0], x[1])
                                    reformats[re_name] = settings[re_name]
                        x = format_types(reformats)
                        q = x.check_rules()
                        if not q[1]:
                            fix.append(f"{key2} - {q[0]}")
                        c = x.check_unique()
                        if not c["bool_status"]:
                            s = f"{key2} - {c['string']}"
                            s_list = s.split("\n")
                            fix.extend(s_list)
                        print
            value.pop("fourchan", None)
            value.pop("bbwchan", None)
    added = "\n".join([f"Added {x}" for x in added if x])
    changed = "\n".join([f"Changed {x}" for x in changed if x])
    fix = "\n".join([f"Fix: {x}" for x in fix if x])
    seperator = "\n"*2
    changed2 = seperator.join([added, changed, fix])
    if not all(x for x in changed2.split("\n") if not x):
        changed2 = changed2.strip()
        if changed2:
            print(f"\n{changed2}")
        if fix:
            string = "\nFix the problems above and then restart the script."
            print(string.upper())
            input()
            exit(0)
    return config, changed2


class config(object):
    def __init__(self, settings={}, supported={}):
        class Settings(object):
            def __init__(self, auto_site_choice="", profile_directories=[".profiles"], export_type="json", max_threads=-1, min_drive_space=0, webhooks={}, exit_on_completion=False, infinite_loop=True, loop_timeout="0", proxies=[], cert="",  random_string=""):
                class webhooks_settings:
                    def __init__(self, option={}) -> None:
                        class webhook_template:
                            def __init__(self, option={}) -> None:
                                self.webhooks = option.get(
                                    'webhooks', [])
                                self.status = option.get(
                                    'status', None)
                                self.hide_sensitive_info = option.get(
                                    'hide_sensitive_info', True)
                                print

                        class auth_webhook:
                            def __init__(self, option={}) -> None:
                                self.succeeded = webhook_template(
                                    option.get('succeeded', {}))
                                self.failed = webhook_template(
                                    option.get('failed', {}))

                        class download_webhook:
                            def __init__(self, option={}) -> None:
                                self.succeeded = webhook_template(
                                    option.get('succeeded', {}))
                        self.global_webhooks = option.get(
                            'global_webhooks', [])
                        self.global_status = option.get(
                            'global_status', True)
                        self.auth_webhook = auth_webhook(
                            option.get('auth_webhook', {}))
                        self.download_webhook = download_webhook(
                            option.get('download_webhook', {}))
                self.auto_site_choice = auto_site_choice
                self.export_type = export_type
                self.profile_directories = profile_directories
                self.max_threads = max_threads
                self.min_drive_space = min_drive_space
                self.webhooks = webhooks_settings(settings.get(
                    'webhooks', webhooks))
                self.exit_on_completion = exit_on_completion
                self.infinite_loop = infinite_loop
                self.loop_timeout = loop_timeout
                self.proxies = proxies
                self.cert = cert
                self.random_string = random_string if random_string else uuid.uuid1().hex

        class Supported(object):
            def __init__(self, onlyfans={}, patreon={}, starsavn={}):
                self.onlyfans = self.OnlyFans(onlyfans)
                self.starsavn = self.StarsAvn(starsavn)

            class OnlyFans:
                def __init__(self, module):
                    self.settings = self.Settings(module.get('settings', {}))

                class Settings():
                    def __init__(self, option={}):
                        class jobs:
                            def __init__(self, option={}) -> None:
                                self.scrape_names = option.get(
                                    'scrape_names', True)
                                self.scrape_paid_content = option.get(
                                    'scrape_paid_content', True)

                        class browser:
                            def __init__(self, option={}) -> None:
                                self.auth = option.get(
                                    'auth', True)

                        class database:
                            def __init__(self, option={}) -> None:
                                self.posts = option.get(
                                    'posts', True)
                                self.comments = option.get(
                                    'comments', True)
                        self.auto_profile_choice = option.get(
                            'auto_profile_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
                        self.browser = browser(option.get(
                            'browser', {}))
                        self.jobs = jobs(option.get(
                            'jobs', {}))
                        self.download_directories = option.get(
                            'download_directories', [".sites"])
                        normpath = os.path.normpath
                        self.file_directory_format = normpath(option.get(
                            'file_directory_format', "{site_name}/{username}/{api_type}/{value}/{media_type}"))
                        self.filename_format = normpath(option.get(
                            'filename_format', "{filename}.{ext}"))
                        self.metadata_directories = option.get(
                            'metadata_directories', [".sites"])
                        self.metadata_directory_format = normpath(option.get(
                            'metadata_directory_format', "{site_name}/{username}/Metadata"))
                        self.delete_legacy_metadata = option.get(
                            'delete_legacy_metadata', False)
                        self.text_length = option.get('text_length', 255)
                        self.video_quality = option.get(
                            'video_quality', "source")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_type = option.get(
                            'ignore_type', "")
                        self.blacklist_name = option.get(
                            'blacklist_name', "")
                        self.webhook = option.get(
                            'webhook', True)

            class StarsAvn:
                def __init__(self, module):
                    self.settings = self.Settings(module.get('settings', {}))

                class Auth:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.sess = option.get('sess', "")
                        self.user_agent = option.get('user_agent', "")

                class Settings():
                    def __init__(self, option={}):
                        class jobs:
                            def __init__(self, option={}) -> None:
                                self.scrape_names = option.get(
                                    'scrape_names', True)
                                self.scrape_paid_content = option.get(
                                    'scrape_paid_content', True)

                        class browser:
                            def __init__(self, option={}) -> None:
                                self.auth = option.get(
                                    'auth', True)
                        self.auto_profile_choice = option.get(
                            'auto_profile_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
                        self.browser = browser(option.get(
                            'browser', {}))
                        self.jobs = jobs(option.get(
                            'jobs', {}))
                        self.download_directories = option.get(
                            'download_directories', [".sites"])
                        normpath = os.path.normpath
                        self.file_directory_format = normpath(option.get(
                            'file_directory_format', "{site_name}/{username}/{api_type}/{value}/{media_type}"))
                        self.filename_format = normpath(option.get(
                            'filename_format', "{filename}.{ext}"))
                        self.metadata_directories = option.get(
                            'metadata_directories', [".sites"])
                        self.metadata_directory_format = normpath(option.get(
                            'metadata_directory_format', "{site_name}/{username}/Metadata"))
                        self.delete_legacy_metadata = option.get(
                            'delete_legacy_metadata', False)
                        self.text_length = option.get('text_length', 255)
                        self.video_quality = option.get(
                            'video_quality', "source")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_type = option.get(
                            'ignore_type', "")
                        self.blacklist_name = option.get(
                            'blacklist_name', "")
                        self.webhook = option.get(
                            'webhook', True)
        self.settings = Settings(**settings)
        self.supported = Supported(**supported)
