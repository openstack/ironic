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

# Wipe the profile registry too so -CreateProfile can always claim the name.
# It lives under the root named by application.ini's Profile=, which only
# $FIREFOX knows, hence the profile itself is kept outside of it.
rm -rf "$FIREFOX_USER_HOME/.mozilla" "$FIREFOX_PROFILE_DIR"

# Start headless purely to write the profile, which exits as soon as it is
# done. Headless means this no longer depends on $DISPLAY being up, as
# -CreateProfile otherwise refuses to run without one.
$FIREFOX -headless -CreateProfile "ironic-vnc $FIREFOX_PROFILE_DIR" || fail "could not create the ironic-vnc profile"

# -CreateProfile exits 0 whether or not it wrote anything.
if [ ! -d "$FIREFOX_PROFILE_DIR" ]; then
    fail "-CreateProfile left no profile in '$FIREFOX_PROFILE_DIR'"
fi

cert-override.py > "$FIREFOX_PROFILE_DIR/cert_override.txt" || fail "cert-override.py failed"

# support a DEBUG variable to aid development
DEBUG=${DEBUG:-0}
args=(-width ${DISPLAY_WIDTH} -height ${DISPLAY_HEIGHT})
args+=(-profile "$FIREFOX_PROFILE_DIR")
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
