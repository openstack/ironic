#!/bin/bash

set -eux

if [ "$READ_ONLY" = "True" ]; then
    viewonly="-viewonly"
else
    viewonly=""
fi

x11vnc $viewonly -nevershared -forever -afteraccept 'start-selenium-browser.py &' -gone 'killall -s SIGTERM python3'