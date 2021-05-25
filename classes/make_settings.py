import copy
from typing import List, Union
from urllib.parse import urlparse
from apis.onlyfans.onlyfans import auth_details
import os

import ujson
from classes.prepare_metadata import format_types, prepare_reformat
import uuid as uuid

def fix(config={}):
    info = config.get("info")
    if not info:
        print("If you're not using >= v7 release, please download said release so the script can properly update your config. \nIf you're using >= v7 release or you don't care about your current config settings, press enter to continue. If script crashes, delete config.")
        input()
    return config


class config(object):
    def __init__(self, info={}, settings={}, supported={}):
        class Info(object):
            def __init__(self) -> None:
                self.version = 7.1

        class Settings(object):
            def __init__(self, auto_site_choice="", profile_directories=[".profiles"], export_type="json", max_threads=-1, min_drive_space=0, helpers={}, webhooks={}, exit_on_completion=False, infinite_loop=True, loop_timeout="0", dynamic_rules_link="https://raw.githubusercontent.com/DATAHOARDERS/dynamic-rules/main/onlyfans.json", proxies=[], cert="",  random_string=""):
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

                class helpers_settings:
                    def __init__(self, option={}) -> None:
                        self.renamer = option.get('renamer', True)
                        self.reformat_media = option.get(
                            'reformat_media', True)
                        self.delete_empty_directories = option.get(
                            'delete_empty_directories', False)
                self.auto_site_choice = auto_site_choice
                self.export_type = export_type
                self.profile_directories = profile_directories
                self.max_threads = max_threads
                self.min_drive_space = min_drive_space
                self.helpers = helpers_settings(
                    settings.get("helpers", helpers))
                self.webhooks = webhooks_settings(settings.get(
                    'webhooks', webhooks))
                self.exit_on_completion = exit_on_completion
                self.infinite_loop = infinite_loop
                self.loop_timeout = loop_timeout
                if "github.com" in dynamic_rules_link:
                    if "raw" not in dynamic_rules_link:
                        parsed_link = urlparse(dynamic_rules_link)
                        path = parsed_link.path.replace("blob/","")
                        dynamic_rules_link = f"https://raw.githubusercontent.com/{path}"
                self.dynamic_rules_link = dynamic_rules_link
                self.proxies = proxies
                self.cert = cert
                self.random_string = random_string if random_string else uuid.uuid1().hex

        def update_site_settings(options) -> dict:
            new_options = copy.copy(options)
            for key, value in options.items():
                if "auto_scrape_names" == key:
                    new_options["auto_model_choice"] = value
                elif "auto_scrape_apis" == key:
                    new_options["auto_api_choice"] = value
            return new_options

        class Supported(object):
            def __init__(self, onlyfans={}, patreon={}, starsavn={}):
                self.onlyfans = self.OnlyFans(onlyfans)
                self.starsavn = self.StarsAvn(starsavn)

            class OnlyFans:
                def __init__(self, module):
                    self.settings = self.Settings(module.get('settings', {}))

                class Settings():
                    def __init__(self, option={}):
                        option = update_site_settings(option)

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
                        self.auto_profile_choice: Union[List] = option.get(
                            'auto_profile_choice', [])
                        self.auto_model_choice = option.get(
                            'auto_model_choice', False)
                        self.auto_media_choice = option.get(
                            'auto_media_choice', "")
                        self.auto_api_choice = option.get(
                            'auto_api_choice', True)
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
                        option = update_site_settings(option)

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
                        self.auto_model_choice = option.get(
                            'auto_model_choice', False)
                        self.auto_media_choice = option.get(
                            'auto_media_choice', "")
                        self.auto_api_choice = option.get(
                            'auto_api_choice', True)
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
        self.info = Info()
        self.settings = Settings(**settings)
        self.supported = Supported(**supported)
