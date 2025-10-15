#!/bin/bash

set -ex

connections=$(ss --no-header state established '( dport = :5900 or sport = :5900 )' | wc -l)

if [ "$connections" -eq 0 ]; then
    killall -s SIGTERM $FIREFOX
else
    echo "Active VNC connection detected, deferring $FIREFOX shutdown."
fi
