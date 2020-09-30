#!/usr/bin/env python3
import tests.main_test as main_test

main_test.version_check()
main_test.check_config()
main_test.check_extra_auth()

if __name__ == "__main__":
    import datascraper.main_datascraper as main_datascraper
    main_datascraper.start_datascraper()
