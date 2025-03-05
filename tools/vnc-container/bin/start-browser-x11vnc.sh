#!/bin/bash

set -eux

x11vnc -nevershared -forever -afteraccept 'start-selenium-browser.py &' -gone 'killall -s SIGTERM python3'