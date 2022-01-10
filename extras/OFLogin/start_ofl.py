from sys import exit
import os
import sys
from seleniumwire import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from user_agent import generate_user_agent


def launch_browser(headers=None, user_agent=None, proxy=None, browser_type="Firefox"):
    options = {}
    if proxy:
        proxy = {
            "http": proxy,
            "https": proxy,
        }
        options["proxy"] = proxy
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        directory = sys._MEIPASS
    else:
        directory = os.path.dirname(__file__)
    driver = None
    if browser_type == "Firefox":
        matches = ["geckodriver.exe", "geckodriver"]
        driver_paths = list(map(lambda match: os.path.join(directory, match), matches))
        found_paths = [
            driver_path for driver_path in driver_paths if os.path.exists(driver_path)
        ]
        if found_paths:
            driver_path = found_paths[0]
            opts = webdriver.FirefoxOptions()
            # opts.add_argument("--headless")
            profile = webdriver.FirefoxProfile()
            if not user_agent:
                user_agent = generate_user_agent()
            profile.set_preference("general.useragent.override", user_agent)
            driver = webdriver.Firefox(
                firefox_profile=profile,
                executable_path=driver_path,
                options=opts,
                seleniumwire_options=options,
            )
        else:
            message = f"Download geckodriver from https://github.com/mozilla/geckodriver/releases/tag/v0.27.0 and paste it in {directory}"
            input(message)
    else:
        driver_path = os.path.join(directory, "chromedriver.exe")
        opts = webdriver.ChromeOptions()
        opts.add_argument(f"--proxy-server={opts}")
        driver = webdriver.Chrome(
            executable_path=driver_path, options=opts, seleniumwire_options=options
        )
    if not driver:
        input("DRIVER NOT FOUND")
        exit(0)
    driver.set_window_size(1920, 1080)
    browser = driver
    if headers:
        browser._client.set_header_overrides(headers=headers)
    return browser


def monitor_cookies(web_browser):
    match = "auth_id"
    status = False
    cookies = None
    while not status:
        cookies = web_browser.get_cookies()
        if any(x for x in cookies if x["name"] == match):
            status = True
            cookies = {v["name"]: v["value"] for v in cookies}
    return cookies


def login(authed, domain, proxy=None):
    auth_details = authed.auth_details
    email = auth_details.email
    password = auth_details.password
    web_browser = None
    cookies = None
    status = False
    while not status:
        print("Opening Browser")
        if web_browser:
            web_browser.close()
        web_browser = launch_browser(user_agent=auth_details.user_agent, proxy=proxy)
        web_browser.get(domain)
        try:
            WebDriverWait(web_browser, 60).until(
                expected_conditions.element_to_be_clickable(
                    (By.CLASS_NAME, "g-btn.m-rounded.m-flex.m-lg.m-login-btn")
                )
            )
        except Exception as e:
            continue
        print
        email_input = web_browser.find_element_by_css_selector("input[type='email']")
        email_input.click()
        email_input.send_keys(email)
        password_input = web_browser.find_element_by_css_selector(
            "input[type='password']"
        )
        password_input.click()
        password_input.send_keys(password)
        login_button = web_browser.find_element_by_class_name(
            "g-btn.m-rounded.m-flex.m-lg.m-login-btn"
        )
        login_button.submit()
        cookies = monitor_cookies(web_browser)
        if cookies:
            auth_details.auth_id = str(cookies["auth_id"])
            auth_details.sess = cookies["sess"]
            status = True
            web_browser.close()
    return cookies
