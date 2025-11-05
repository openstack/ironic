#!/usr/bin/env python3

import json
import os
import requests
import urllib
import sys

REDFISH_SUPPORTED = {
    "Dell",
    "Hpe",
    "Supermicro",
}

def discover_app(app_name, app_info):
    if app_name == "fake":
        return "fake"
    if app_name == "redfish-graphical":
        # Make an unauthenticated redfish request
        # to discover which console class to use
        url = app_info["address"] + app_info.get("root_prefix", "/redfish/v1")
        verify = app_info.get("verify_ca", True)
        r = requests.get(url, verify=verify, timeout=60).json()
        oem = ",".join(r["Oem"].keys())
        if oem in REDFISH_SUPPORTED:
            return oem
        raise Exception(f"Unsupported {app_name} vendor {oem}")

    raise Exception(f"Unknown app name {app_name}")


def main():
    app_name = os.environ.get("APP")
    app_info = json.loads(os.environ.get("APP_INFO"))
    print(discover_app(app_name, app_info))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(urllib.parse.quote(str(e)))
        sys.exit(1)
    sys.exit(0)
