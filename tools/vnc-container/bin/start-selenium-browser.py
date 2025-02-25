#!/usr/bin/env python3

import json
import os
import requests
from requests import auth
import signal
import sys
import time
from urllib import parse as urlparse

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.common import exceptions


class BaseApp:

    def __init__(self, app_info):
        self.app_info = app_info

    @property
    def url(self):
        pass

    def handle_exit(self, signum, frame):
        print("got SIGTERM, quitting")
        self.driver.quit()
        sys.exit(0)

    def start(self, driver):
        self.driver = driver
        signal.signal(signal.SIGTERM, self.handle_exit)


class FakeApp(BaseApp):

    @property
    def url(self):
        return "file:///drivers/fake/index.html"


class RedfishApp(BaseApp):

    @property
    def base_url(self):
        return self.app_info["address"]

    @property
    def redfish_url(self):
        return self.base_url + self.app_info.get("root_prefix", "/redfish/v1")

    def disable_right_click(self, driver):
        # disable right-click menu
        driver.execute_script(
            'window.addEventListener("contextmenu", function(e) '
            "{ e.preventDefault(); })"
        )


class IdracApp(RedfishApp):

    @property
    def url(self):
        username = self.app_info["username"]
        password = self.app_info["password"]
        verify = self.app_info.get("verify_ca", True)
        kvm_session_url = (f"{self.redfish_url}/Managers/iDRAC.Embedded.1/Oem/"
                           "Dell/DelliDRACCardService/Actions/DelliDRACCardService.GetKVMSession")
        netloc = urlparse.urlparse(self.base_url).netloc

        r = requests.post(
            kvm_session_url,
            verify=verify,
            timeout=60,
            auth=auth.HTTPBasicAuth(username, password),
            json={"SessionTypeName": "idrac-graphical"},
        ).json()
        temp_username = r["TempUsername"]
        temp_password = r["TempPassword"]
        url = (f"{self.base_url}/restgui/vconsole/index.html?ip={netloc}&"
               f"kvmport=443&title=idrac-graphical&VCSID={temp_username}&VCSID2={temp_password}")
        return url

    def start(self, driver):
        super(IdracApp, self).start(driver)
        # wait for the full screen button
        wait = WebDriverWait(
            driver,
            timeout=10,
            poll_frequency=0.2,
            ignored_exceptions=[exceptions.NoSuchElementException],
        )
        wait.until(
            lambda d: driver.find_element(By.TAG_NAME, value="full-screen")
            or True
        )
        fs_tag = driver.find_element(By.TAG_NAME, value="full-screen")
        fs_tag.find_element(By.TAG_NAME, "button").click()


class IloApp(RedfishApp):

    @property
    def url(self):
        return self.base_url + "/irc.html"

    def login(self, driver):

        username = self.app_info["username"]
        password = self.app_info["password"]
        # wait for the username field to be enabled then perform login
        wait = WebDriverWait(
            driver,
            timeout=10,
            poll_frequency=0.2,
            ignored_exceptions=[exceptions.NoSuchElementException],
        )
        wait.until(
            lambda d: driver.find_element(By.ID, value="username") or True
        )

        username_field = driver.find_element(By.ID, value="username")
        wait = WebDriverWait(
            driver,
            timeout=5,
            poll_frequency=0.2,
            ignored_exceptions=[exceptions.ElementNotInteractableException],
        )
        wait.until(lambda d: username_field.send_keys(username) or True)

        driver.find_element(By.ID, value="password").send_keys(password)
        driver.find_element(By.ID, value="login-form__submit").click()

    def start(self, driver):
        super(IloApp, self).start(driver)

        # Detect iLO 6 vs 5 based on whether a message box or a login form
        # is presented
        try:
            driver.find_element(By.CLASS_NAME, value="loginBoxRestrictWidth")
            is_ilo6 = True
        except exceptions.NoSuchElementException:
            is_ilo6 = False

        if is_ilo6:
            # iLO 6 has an inline login which matches the main login
            self.login(driver)
            self.disable_right_click(driver)
            self.full_screen(driver)
            return

        # load the main login page
        driver.get(self.base_url)

        # full screen content is shown in an embedded iframe
        iframe = driver.find_element(By.ID, "appFrame")
        driver.switch_to.frame(iframe)

        self.login(driver)

        # wait for <body id="app-container"> to exist, which indicates
        # the login form has submitted and session cookies are now set
        wait = WebDriverWait(
            driver,
            timeout=10,
            poll_frequency=0.2,
            ignored_exceptions=[exceptions.NoSuchElementException],
        )
        wait.until(
            lambda d: driver.find_element(By.ID, value="app-container")
            or True
        )

        # load the actual console
        driver.get(self.url)
        self.disable_right_click(driver)
        self.full_screen(driver)

    def full_screen(self, driver):
        # make console full screen to hide menu
        fs_button = driver.find_element(
            By.CLASS_NAME, value="btnVideoFullScreen"
        )
        wait = WebDriverWait(
            driver,
            timeout=20,
            poll_frequency=0.2,
            ignored_exceptions=[
                exceptions.ElementNotInteractableException,
                exceptions.ElementClickInterceptedException,
            ],
        )
        wait.until(lambda d: fs_button.click() or True)


class SupermicroApp(RedfishApp):

    @property
    def url(self):
        return self.base_url

    def start(self, driver):
        super(SupermicroApp, self).start(driver)
        username = self.app_info["username"]
        password = self.app_info["password"]

        # populate login and submit
        driver.find_element(By.NAME, value="name").send_keys(username)
        driver.find_element(By.ID, value="pwd").send_keys(password)
        driver.find_element(By.ID, value="login_word").click()

        # navigate down some iframes
        iframe = driver.find_element(By.ID, "TOPMENU")
        driver.switch_to.frame(iframe)

        iframe = driver.find_element(By.ID, "frame_main")
        driver.switch_to.frame(iframe)

        wait = WebDriverWait(
            driver,
            timeout=30,
            poll_frequency=0.2,
            ignored_exceptions=[
                exceptions.NoSuchElementException,
                exceptions.ElementNotInteractableException,
            ],
        )
        wait.until(lambda d: driver.find_element(By.ID, value="img1") or True)

        # launch the console by waiting for the console preview image to be
        # loaded and clickable
        def snapshot_wait(d):
            try:
                img1 = driver.find_element(By.ID, value="img1")
            except exceptions.NoSuchElementException:
                print("img1 doesn't exist yet")
                return False

            if "Snapshot" not in img1.get_attribute("src"):
                print("img1 src not a console snapshot yet")
                return False
            if not img1.get_attribute("complete") == "true":
                print("img1 console snapshot not loaded yet")
                return False
            try:
                img1.click()
            except exceptions.ElementNotInteractableException:
                print("img1 not clickable yet")
                return False
            return True

        wait = WebDriverWait(driver, timeout=30, poll_frequency=1)
        wait.until(snapshot_wait)

        # self.disable_right_click(driver)


def start_driver(url, app_info):
    print(f"starting app with url {url}")
    opts = webdriver.ChromeOptions()
    opts.binary_location = "/usr/bin/chromium-browser"
    # opts.enable_bidi = True
    if url:
        opts.add_argument(f"--app={url}")

    verify = app_info.get("verify_ca", True)
    if not verify:
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--ignore-ssl-errors")

    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-plugins-discovery")

    opts.add_argument("--disable-context-menu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    opts.add_argument("--window-position=0,0")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    if "DISPLAY_WIDTH" in os.environ and "DISPLAY_HEIGHT" in os.environ:
        width = int(os.environ["DISPLAY_WIDTH"])
        height = int(os.environ["DISPLAY_HEIGHT"])
        opts.add_argument(f"--window-size={width},{height}")
    if "CHROME_ARGS" in os.environ:
        for arg in os.environ["CHROME_ARGS"].split(" "):
            opts.add_argument(arg)

    driver = webdriver.Chrome(options=opts)
    driver.delete_all_cookies()
    driver.set_window_position(0, 0)

    return driver


def discover_app(app_name, app_info):
    if app_name == "fake":
        return FakeApp
    if app_name == "redfish-graphical":
        # Make an unauthenticated redfish request
        # to discover which console class to use
        url = app_info["address"] + app_info.get("root_prefix", "/redfish/v1")
        verify = app_info.get("verify_ca", True)
        r = requests.get(url, verify=verify, timeout=60).json()
        oem = ",".join(r["Oem"].keys())
        if "Hpe" in oem:
            return IloApp
        if "Dell" in oem:
            return IdracApp
        if "Supermicro" in oem:
            return SupermicroApp
        raise Exception(f"Unsupported {app_name} vendor {oem}")

    raise Exception(f"Unknown app name {app_name}")


def main():
    app_name = os.environ.get("APP")
    print("got app info " + os.environ.get("APP_INFO"))
    app_info = json.loads(os.environ.get("APP_INFO"))
    app_class = discover_app(app_name, app_info)

    app = app_class(app_info)

    driver = start_driver(url=app.url, app_info=app_info)
    print(f"got driver {driver}")

    print(f"Running app {app_name}")
    app.start(driver)
    while True:
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())
