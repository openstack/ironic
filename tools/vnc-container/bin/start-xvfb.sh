#!/bin/bash

set -eux

xvfb-run -s "-screen 0 ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x24" start-browser-x11vnc.sh