#!/bin/bash

set -ex

if pgrep -x firefox >/dev/null; then
    echo "Firefox is already running. Exiting."
    exit 0
fi

rm -rf ~/.mozilla/firefox

firefox -CreateProfile ironic-vnc

pushd ~/.mozilla/firefox/*.ironic-vnc
cert-override.py > cert_override.txt
popd

# support a DEBUG variable to aid development
DEBUG=${DEBUG:-0}
if [ "$DEBUG" = "2" ]; then
    # show tabs and a javascript console
    firefox -width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc -jsconsole &
elif [ "$DEBUG" = "1" ]; then
    # show tabs
    firefox -width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc &
else
    # fully locked down kiosk mode
    firefox -width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc --kiosk &
fi
