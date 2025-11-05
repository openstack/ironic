#!/usr/bin/env python3

import os

import json

app_name = os.environ.get("APP", "fake")
app_info = json.loads(os.environ.get("APP_INFO"))
debug = int(os.environ.get("DEBUG", 0))
verify = app_info.get("verify_ca", True)
error = os.environ.get("ERROR", "")

if app_name == "fake":
    # Extensions cannot set file:// URLs so special case the fake driver
    homepage = "file:///drivers/fake/index.html"
else:
    homepage = "file:///drivers/launch/index.html"
    if error:
        homepage += f"?error={error}"

policies = {
    "AppAutoUpdate": False,
    "AutofillAddressEnabled": False,
    "AutofillCreditCardEnabled": False,
    "DisableAppUpdate": True,
    "DisableFirefoxScreenshots": True,
    "DisableFirefoxStudies": True,
    "DisableFirefoxStudies_comment": "Disable Firefox studies",
    "DisablePocket": True,
    "DisableSystemAddonUpdate": True,
    "DisableTelemetry": True,
    "DontCheckDefaultBrowser": True,
    "Homepage": {
        "URL": homepage,
        "StartPage": "homepage",
    },
    "NoDefaultBookmarks": True,
    "OfferToSaveLogins": False,
    "OverrideFirstRunPage": "",
    "OverridePostUpdatePage": "",
    "PasswordManagerEnabled": False,
    "Preferences": {
        "security.ssl.enable_ocsp_stapling": {
            "Value": verify,
            "Status": "locked",
        },
        "dom.disable_open_during_load": {
            "Value": False,
            "Status": "locked",
        },
    },
    "PrintingEnabled": False,
    "PromptForDownloadLocation": False,
    "SanitizeOnShutdown": True,
    "SkipTermsOfUse": True,
    "StartDownloadsInTempDirectory": True,
    "WebsiteFilter": {
        "Block": ["<all_urls>"],
        "Exceptions": ["file:///drivers/*"],
    },
}

if not debug:
    policies.update(
        {
            "BlockAboutConfig": True,
            "BlockAboutAddons": True,
            "BlockAboutProfiles": True,
            "BlockAboutSupport": True,
        }
    )

address = app_info.get("address")
if address:
    policies["WebsiteFilter"]["Exceptions"].append(
        f"{address}/*"
    )

print(json.dumps({"policies": policies}, indent=2))
