class start(object):
    def __init__(self, settings={}, supported={}):
        class Settings(object):
            def __init__(self, auto_site_choice="", export_type="json", multithreading=True, exit_on_completion=False, infinite_loop=True, loop_timeout="0", socks5_proxy="", global_user_agent=""):
                self.auto_site_choice = auto_site_choice
                self.export_type = export_type
                self.multithreading = multithreading
                self.exit_on_completion = exit_on_completion
                self.infinite_loop = infinite_loop
                self.loop_timeout = loop_timeout
                self.socks5_proxy = socks5_proxy
                self.global_user_agent = global_user_agent

        class Supported(object):
            def __init__(self, onlyfans={}, starsavn={}, fourchan={}, bbwchan={}):
                self.onlyfans = self.OnlyFans(onlyfans)
                self.starsavn = self.StarsAvn(starsavn)
                self.fourchan = self.FourChan(fourchan)
                self.bbwchan = self.BBWChan(bbwchan)

            class OnlyFans:
                def __init__(self, module):
                    self.auth = module.get('auth', self.Auth())
                    self.settings = module.get('settings', self.Settings())
                    self.extra_auth_settings = module.get('extra_auth_settings', self.ExtraAuthSettings())

                class Auth:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.auth_id = option.get('auth_id', "")
                        self.auth_hash = option.get('auth_hash', "")
                        self.sess = option.get('sess', "")
                        self.fp = option.get('fp', "")
                        self.app_token = option.get(
                            'app_token', '33d57ade8c02dbc5a333db99ff9ae26a')
                        self.user_agent = option.get('user_agent', "")
                        self.support_2fa = option.get('support_2fa', True)

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
                        self.directory = option.get('directory', "")
                        self.file_name_format = option.get(
                            'file_name_format', "{file_name}.{ext}")
                        self.text_length = option.get('text_length', "")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_unfollowed_accounts = option.get(
                            'ignore_unfollowed_accounts', "")
                        self.export_metadata = option.get(
                            'export_metadata', True)
                        self.delete_legacy_metadata = option.get(
                            'delete_legacy_metadata', False)
                        self.sort_free_paid_posts = option.get(
                            'sort_free_paid_posts', True)
                        self.blacklist_name = option.get(
                            'blacklist_name', "")

                class ExtraAuthSettings:
                    def __init__(self, option={}):
                        self.extra_auth = option.get('extra_auth', False)
                        self.choose_auth = option.get('choose_auth', False)
                        self.merge_auth = option.get('merge_auth', False)

            class StarsAvn:
                def __init__(self, module):
                    self.auth = module.get('auth', self.Auth())
                    self.settings = module.get('settings', self.Settings())
                    self.extra_auth_settings = module.get('extra_auth_settings', self.ExtraAuthSettings())

                class Auth:
                    def __init__(self, option={}):
                        self.username = option.get('username', "")
                        self.sess = option.get('sess', "")
                        self.user_agent = option.get('user_agent', "")

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.auto_scrape_apis = option.get(
                            'auto_scrape_apis', True)
                        self.directory = option.get('directory', "")
                        self.file_name_format = option.get(
                            'file_name_format', "{file_name}.{ext}")
                        self.text_length = option.get('text_length', "")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
                        self.ignore_unfollowed_accounts = option.get(
                            'ignore_unfollowed_accounts', "")
                        self.export_metadata = option.get(
                            'export_metadata', True)
                        self.blacklist_name = option.get(
                            'blacklist_name', "")

                class ExtraAuthSettings:
                    def __init__(self, option={}):
                        self.extra_auth = option.get('extra_auth', False)
                        self.choose_auth = option.get('choose_auth', False)
                        self.merge_auth = option.get('merge_auth', False)

            class FourChan:
                def __init__(self, module):
                    self.auth = module.get('auth', self.Auth())
                    self.settings = module.get('settings', self.Settings())

                class Auth:
                    def __init__(self, option={}):
                        pass

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.directory = option.get('directory', "")
                        self.file_name_format = option.get(
                            'file_name_format', "{file_name}.{ext}")
                        self.text_length = option.get('text_length', "")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.boards = option.get(
                            'boards', [])
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])

            class BBWChan:
                def __init__(self, module):
                    self.auth = module.get('auth', self.Auth())
                    self.settings = module.get('settings', self.Settings())

                class Auth:
                    def __init__(self, option={}):
                        pass

                class Settings:
                    def __init__(self, option={}):
                        self.auto_choice = option.get('auto_choice', "")
                        self.auto_scrape_names = option.get(
                            'auto_scrape_names', False)
                        self.directory = option.get('directory', "")
                        self.file_name_format = option.get(
                            'file_name_format', "{file_name}.{ext}")
                        self.text_length = option.get('text_length', "")
                        self.overwrite_files = option.get(
                            'overwrite_files', False)
                        self.date_format = option.get(
                            'date_format', "%d-%m-%Y")
                        self.boards = option.get(
                            'boards', [])
                        self.ignored_keywords = option.get(
                            'ignored_keywords', [])
        self.settings = Settings(**settings)
        self.supported = Supported(**supported)
