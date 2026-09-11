#!/bin/bash

set -ex

# x11vnc ignores the exit status of this script, so a silent failure leaves
# it exporting an empty X display, which looks like a black console.
fail() {
    echo "FATAL: start-firefox.sh: $*" >&2
    echo "FATAL: no browser was started, the console will be a black screen" >&2
    exit 1
}

trap 'fail "unexpected failure at line $LINENO"' ERR

if pgrep -x $FIREFOX >/dev/null; then
    echo "Firefox is already running. Exiting."
    exit 0
fi

rm -rf $FIREFOX_CONFIG_DIR

$FIREFOX -CreateProfile ironic-vnc || fail "could not create the ironic-vnc profile"

pushd $FIREFOX_CONFIG_DIR/*.ironic-vnc
cert-override.py > cert_override.txt || fail "cert-override.py failed"
popd

# support a DEBUG variable to aid development
DEBUG=${DEBUG:-0}
args=(-width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT} -P ironic-vnc)
if [ "$DEBUG" = "2" ]; then
    # show tabs and a javascript console
    args+=(-jsconsole)
elif [ "$DEBUG" = "1" ]; then
    # show tabs
    :
else
    # fully locked down kiosk mode
    args+=(--kiosk)
fi

$FIREFOX "${args[@]}" &
firefox_pid=$!

# Backgrounding means a browser that dies at startup still exits 0 here.
sleep 2
kill -0 $firefox_pid 2>/dev/null || fail "$FIREFOX exited immediately after launch"
