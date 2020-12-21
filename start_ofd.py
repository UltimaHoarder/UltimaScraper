#!/usr/bin/env python3
import tests.main_test as main_test
import os
import logging

main_test.version_check()
main_test.check_config()
main_test.check_profiles()

if __name__ == "__main__":
    import datascraper.main_datascraper as main_datascraper
    import helpers.main_helper as main_helper
    log_error = main_helper.setup_logger('errors', 'errors.log')
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger("").addHandler(console)
    config_path = os.path.join('.settings', 'config.json')
    json_config, json_config2 = main_helper.get_config(config_path)
    json_settings = json_config["settings"]
    json_sites = json_config["supported"]
    domain = json_settings["auto_site_choice"]
    string, site_names = main_helper.module_chooser(domain, json_sites)
    while True:
        try:
            if domain:
                if site_names:
                    site_name = domain
                else:
                    print(string)
                    continue
            else:
                print(string)
                x = input()
                if x == "x":
                    break
                x = int(x)
                site_name = site_names[x]
            site_name_lower = site_name.lower()
            main_datascraper.start_datascraper(json_config, site_name_lower)
        except Exception as e:
            log_error.exception(e)
            input()
