#!/bin/bash

set -e -x

if [ ! -x /usr/bin/jq ]; then
    echo "This script relies on 'jq' to process JSON output."
    echo "Please install it before continuing."
    exit 1
fi

OS_AUTH_TOKEN=$(openstack token issue | grep ' id ' | awk '{print $4}')
IRONIC_URL="http://127.0.0.1:6385"

export OS_AUTH_TOKEN IRONIC_URL

function GET {
    # GET $RESOURCE
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H 'X-OpenStack-Ironic-API-Version: 1.22' \
            ${IRONIC_URL}/$1 | jq -S '.'
}

function POST {
    # POST $RESOURCE $FILENAME
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H 'X-OpenStack-Ironic-API-Version: 1.22' \
            -H "Content-Type: application/json" \
            -X POST --data @$2 \
            ${IRONIC_URL}/$1 | jq -S '.'
}

function PATCH {
    # POST $RESOURCE $FILENAME
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H 'X-OpenStack-Ironic-API-Version: 1.22' \
            -H "Content-Type: application/json" \
            -X PATCH --data @$2 \
            ${IRONIC_URL}/$1 | jq -S '.'
}

function PUT {
    # PUT $RESOURCE $FILENAME
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H 'X-OpenStack-Ironic-API-Version: 1.22' \
            -H "Content-Type: application/json" \
            -X PUT --data @$2 \
            ${IRONIC_URL}/$1
}

pushd source/samples

###########
# ROOT APIs
GET '' > api-root-response.json

GET 'v1' > api-v1-root-response.json


###########
# DRIVER APIs
GET v1/drivers > drivers-list-response.json
GET v1/drivers/agent_ipmitool > driver-get-response.json
GET v1/drivers/agent_ipmitool/properties > driver-property-response.json
GET v1/drivers/agent_ipmitool/raid/logical_disk_properties > driver-logical-disk-properties-response.json

GET v1/drivers/agent_ipmitool/vendor_passthru/methods > driver-passthru-methods-response.json



#########
# CHASSIS

POST v1/chassis chassis-create-request.json > chassis-show-response.json
CID=$(cat chassis-show-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$CID" == "" ]; then
    exit 1
else
    echo "Chassis created. UUID: $CID"
fi

GET v1/chassis > chassis-list-response.json

GET v1/chassis/detail > chassis-list-details-response.json

PATCH v1/chassis/$CID chassis-update-request.json > chassis-update-response.json

# skip  GET /v1/chassis/$UUID because the response is same as POST


#######
# NODES

# Create a node with a real driver, but missing ipmi_address,
# then do basic commands with it
POST v1/nodes node-create-request.json > node-create-response.json
NID=$(cat node-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$NID" == "" ]; then
    exit 1
else
    echo "Node created. UUID: $NID"
fi

# get the list of passthru methods from agent* driver
GET v1/nodes/$NID/vendor_passthru/methods > node-vendor-passthru-response.json

# Change to the fake driver and then move the node into the AVAILABLE
# state without saving any output.
# NOTE that these three JSON files are not included in the docs
PATCH v1/nodes/$NID node-update-driver.json
PUT v1/nodes/$NID/states/provision node-set-manage-state.json
PUT v1/nodes/$NID/states/provision node-set-available-state.json

GET v1/nodes/$NID/validate > node-validate-response.json

PUT v1/nodes/$NID/states/power node-set-power-off.json
GET v1/nodes/$NID/states > node-get-state-response.json

GET v1/nodes > nodes-list-response.json
GET v1/nodes/detail > nodes-list-details-response.json
GET v1/nodes/$NID > node-show-response.json

# Put the Node in maintenance mode, then continue doing everything else
PUT v1/nodes/$NID/maintenance node-maintenance-request.json

###########
# PORTS

# Before we can create a port, we must
# write NODE ID into the create request document body
sed -i "s/.*node_uuid.*/    \"node_uuid\": \"$NID\",/" port-create-request.json

POST v1/ports port-create-request.json > port-create-response.json
PID=$(cat port-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$PID" == "" ]; then
    exit 1
else
    echo "Port created. UUID: $PID"
fi

GET v1/ports > port-list-respone.json
GET v1/ports/detail > port-list-detail-response.json
PATCH v1/ports/$PID port-update-request.json > port-update-response.json

# skip GET $PID because same result as POST
# skip DELETE

################
# NODE PORT APIs

GET v1/nodes/$NID/ports > node-port-list-response.json
GET v1/nodes/$NID/ports/detail > node-port-detail-response.json


############
# LOOKUP API

GET v1/lookup?node_uuid=$NID > lookup-node-response.json


#####################
# NODES MANAGEMENT API
# These need to be done while the node is in maintenance mode,
# and the node's driver is "fake", to avoid potential races
# with internal processes that lock the Node

# this corrects an intentional ommission in some of the samples
PATCH v1/nodes/$NID node-update-driver-info-request.json > node-update-driver-info-response.json

GET v1/nodes/$NID/management/boot_device/supported > node-get-supported-boot-devices-response.json
PUT v1/nodes/$NID/management/boot_device node-set-boot-device.json
GET v1/nodes/$NID/management/boot_device > node-get-boot-device-response.json
