#!/bin/bash

set -ex

connections=$(ss --no-header state established '( dport = :5900 or sport = :5900 )' | wc -l)

if [ "$connections" -eq 0 ]; then
    # Signal the main process to gracefully shut down the browser.
    # The main process handles navigating tabs to about:blank
    # (closing console websockets) before killing the browser.
    curl -s -X POST http://localhost:8888/browser-shutdown

    # Wait until firefox has actually exited
    while pgrep -x $FIREFOX >/dev/null 2>&1; do
        sleep 1
    done
else
    echo "Active VNC connection detected, deferring $FIREFOX shutdown."
fi
