#!/bin/bash

set -ex


extension_path="/usr/share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}/@ironic-console.openstack.org"

set +e
APP_NAME=$(discover-app.py)
if [ $? -ne 0 ]; then
    export ERROR="${APP_NAME}"
    APP_NAME="error"
fi

set -e

cat << EOF > "${extension_path}/config.js"
let config = {
    app: "${APP_NAME}",
    app_info: ${APP_INFO}
};
EOF

sed -i "s#APP_NAME#${APP_NAME}#g" "${extension_path}/manifest.json"

mkdir -p /etc/firefox/policies
policies.py > /etc/firefox/policies/policies.json

READ_ONLY=${READ_ONLY:-False}
if [ "$READ_ONLY" = "True" ]; then
    viewonly="-viewonly -nocursor"
else
    viewonly=""
fi

export X11VNC_CREATE_GEOM=${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x24
runuser -u firefox -- x11vnc -ncache 10 $viewonly -create -shared -forever -afteraccept start-firefox.sh -gone stop-firefox.sh