import os
from classes.prepare_metadata import format_types
import uuid as uuid


def fix(config={}):
    added = []
    changed = []
    fix = []
    for key, value in config.items():
        if key == "supported":
            for key2, value2 in value.items():
                for key3, settings in value2.items():
                    if key3 == "settings":
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
                        filename_format = settings.pop(
                            "file_name_format",None)
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
            def __init__(self, auto_site_choice="", profile_directories=[".profiles"], export_type="json", max_threads=-1, min_drive_space=0, webhooks=[], exit_on_completion=False, infinite_loop=True, loop_timeout="0", socks5_proxy=[], cert="", global_user_agent="", random_string=""):
                self.auto_site_choice = auto_site_choice
                self.export_type = export_type
                self.profile_directories = profile_directories
                self.max_threads = max_threads
                self.min_drive_space = min_drive_space
                self.webhooks = webhooks
                self.exit_on_completion = exit_on_completion
                self.infinite_loop = infinite_loop
                self.loop_timeout = loop_timeout
                self.socks5_proxy = socks5_proxy
                self.cert = cert
                self.random_string = random_string if random_string else uuid.uuid1().hex
                self.global_user_agent = global_user_agent

        class Supported(object):
            def __init__(self, onlyfans={}, patreon={}, starsavn={}, fourchan={}, bbwchan={}):
                self.onlyfans = self.OnlyFans(onlyfans)
                self.patreon = self.Patreon(patreon)
                self.starsavn = self.StarsAvn(starsavn)
                self.fourchan = self.FourChan(fourchan)
                self.bbwchan = self.BBWChan(bbwchan)

            class OnlyFans:
                def __init__(self, module):
                    self.auth = self.Auth(module.get('auth', {}))
                    self.settings = self.Settings(module.get('settings', {}))
                    self.extra_auth_settings = self.ExtraAuthSettings(
                        module.get('extra_auth_settings', {}))

                class Auth:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.auth_id = option.get('auth_id', "")
                        self.auth_hash = option.get('auth_hash', "")
                        self.auth_uniq_ = option.get('auth_uniq_', "")
                        self.sess = option.get('sess', "")
                        self.app_token = option.get(
                            'app_token', '33d57ade8c02dbc5a333db99ff9ae26a')
                        self.user_agent = option.get('user_agent', "")
                        self.support_2fa = option.get('support_2fa', True)

                class Settings():
                    def __init__(self, option={}):
                        class jobs:
                            def __init__(self, option={}) -> None:
                                self.scrape_names = option.get(
                                    'scrape_names', True)
                                self.scrape_paid_content = option.get(
                                    'scrape_paid_content', True)
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
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
                        self.text_length = option.get('text_length', 255)
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_type = option.get(
                            'ignore_type', "")
                        self.export_metadata = option.get(
                            'export_metadata', True)
                        self.delete_legacy_metadata = option.get(
                            'delete_legacy_metadata', False)
                        self.blacklist_name = option.get(
                            'blacklist_name', "")
                        self.webhook = option.get(
                            'webhook', True)

                class ExtraAuthSettings:
                    def __init__(self, option={}):
                        self.extra_auth = option.get('extra_auth', False)
                        self.choose_auth = option.get('choose_auth', False)
                        self.merge_auth = option.get('merge_auth', False)

            class StarsAvn:
                def __init__(self, module):
                    self.auth = self.Auth(module.get('auth', {}))
                    self.settings = self.Settings(module.get('settings', {}))
                    self.extra_auth_settings = self.ExtraAuthSettings(
                        module.get('extra_auth_settings', {}))

                class Auth:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.sess = option.get('sess', "")
                        self.user_agent = option.get('user_agent', "")

                class Settings:
                    def __init__(self, option={}):
                        class jobs:
                            def __init__(self, option={}) -> None:
                                self.scrape_names = option.get(
                                    'scrape_names', True)
                                self.scrape_paid_content = option.get(
                                    'scrape_paid_content', True)
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
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
                        self.text_length = option.get('text_length', "255")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_type = option.get(
                            'ignore_type', "")
                        self.export_metadata = option.get(
                            'export_metadata', True)
                        self.blacklist_name = option.get(
                            'blacklist_name', "")
                        self.webhook = option.get(
                            'webhook', True)

                class ExtraAuthSettings:
                    def __init__(self, option={}):
                        self.extra_auth = option.get('extra_auth', False)
                        self.choose_auth = option.get('choose_auth', False)
                        self.merge_auth = option.get('merge_auth', False)

            class FourChan:
                def __init__(self, module):
                    self.auth = self.Auth(module.get('auth', {}))
                    self.settings = self.Settings(module.get('settings', {}))

                class Auth:
                    def __init__(self, option={}):
                        pass

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
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
                        self.text_length = option.get('text_length', "255")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.boards = option.get(
                            'boards', [])
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.webhook = option.get(
                            'webhook', True)

            class BBWChan:
                def __init__(self, module):
                    self.auth = self.Auth(module.get('auth', {}))
                    self.settings = self.Settings(module.get('settings', {}))

                class Auth:
                    def __init__(self, option={}):
                        pass

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
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
                        self.text_length = option.get('text_length', "255")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.boards = option.get(
                            'boards', [])
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.webhook = option.get(
                            'webhook', True)

            class Patreon:
                def __init__(self, module):
                    self.auth = self.Auth(module.get('auth', {}))
                    self.settings = self.Settings(module.get('settings', {}))
                    self.extra_auth_settings = self.ExtraAuthSettings(
                        module.get('extra_auth_settings', {}))

                class Auth:
                    def __init__(self, option={}):
                        self.cf_clearance = option.get('cf_clearance', "")
                        self.session_id = option.get('session_id', "")
                        self.user_agent = option.get('user_agent', "")
                        self.support_2fa = option.get('support_2fa', True)

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
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
                        self.text_length = option.get('text_length', "255")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_type = option.get(
                            'ignore_type', "")
                        self.export_metadata = option.get(
                            'export_metadata', True)
                        self.delete_legacy_metadata = option.get(
                            'delete_legacy_metadata', False)
                        self.blacklist_name = option.get(
                            'blacklist_name', "")
                        self.webhook = option.get(
                            'webhook', True)

                class ExtraAuthSettings:
                    def __init__(self, option={}):
                        self.extra_auth = option.get('extra_auth', False)
                        self.choose_auth = option.get('choose_auth', False)
                        self.merge_auth = option.get('merge_auth', False)
        self.settings = Settings(**settings)
        self.supported = Supported(**supported)


class extra_auth(object):
    def __init__(self, supported={}):
        class Supported(object):
            def __init__(self, onlyfans={}, patreon={}, starsavn={}):
                self.onlyfans = self.OnlyFans(onlyfans)
                self.patreon = self.Patreon(patreon)
                self.starsavn = self.StarsAvn(starsavn)

            class OnlyFans:
                def __init__(self, module):
                    if "extra_auth" in module:
                        module["auths"] = module["extra_auth"]
                    auths = module.get("auths", [{}])
                    self.auths = []
                    for auth in auths:
                        self.auths.append(self.Auths(auth))

                class Auths:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.auth_id = option.get('auth_id', "")
                        self.auth_hash = option.get('auth_hash', "")
                        self.auth_uniq_ = option.get('auth_uniq_', "")
                        self.sess = option.get('sess', "")
                        self.app_token = option.get(
                            'app_token', '33d57ade8c02dbc5a333db99ff9ae26a')
                        self.user_agent = option.get('user_agent', "")
                        self.support_2fa = option.get('support_2fa', True)

            class Patreon:
                def __init__(self, module):
                    if "extra_auth" in module:
                        module["auths"] = module["extra_auth"]
                    auths = module.get("auths", [{}])
                    self.auths = []
                    for auth in auths:
                        self.auths.append(self.Auths(auth))

                class Auths:
                    def __init__(self, option={}):
                        self.cf_clearance = option.get('cf_clearance', "")
                        self.session_id = option.get('session_id', "")
                        self.user_agent = option.get('user_agent', "")
                        self.support_2fa = option.get('support_2fa', True)

            class StarsAvn:
                def __init__(self, module):
                    if "extra_auth" in module:
                        module["auths"] = module["extra_auth"]
                    auths = module.get("auths", [{}])
                    self.auths = []
                    for auth in auths:
                        self.auths.append(self.Auths(auth))

                class Auths:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.sess = option.get('sess', "")
                        self.user_agent = option.get('user_agent', "")
        self.supported = Supported(**supported)
