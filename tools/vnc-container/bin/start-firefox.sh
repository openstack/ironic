#!/bin/bash

set -ex

if pgrep -x $FIREFOX >/dev/null; then
    echo "Firefox is already running. Exiting."
    exit 0
fi

rm -rf $FIREFOX_CONFIG_DIR

$FIREFOX -CreateProfile ironic-vnc

pushd $FIREFOX_CONFIG_DIR/*.ironic-vnc
cert-override.py > cert_override.txt
popd

# support a DEBUG variable to aid development
DEBUG=${DEBUG:-0}
if [ "$DEBUG" = "2" ]; then
    # show tabs and a javascript console
    $FIREFOX -width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc -jsconsole &
elif [ "$DEBUG" = "1" ]; then
    # show tabs
    $FIREFOX -width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc &
else
    # fully locked down kiosk mode
    $FIREFOX -width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc --kiosk &
fi
