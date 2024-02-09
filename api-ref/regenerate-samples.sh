#!/bin/bash

set -e -x

if [ ! -x /usr/bin/jq ]; then
    echo "This script relies on 'jq' to process JSON output."
    echo "Please install it before continuing."
    exit 1
fi

OS_AUTH_TOKEN=$(openstack token issue | grep ' id ' | awk '{print $4}')
IRONIC_URL="http://127.0.0.1:6385"

IRONIC_API_VERSION="1.55"

export OS_AUTH_TOKEN IRONIC_URL

DOC_BIOS_UUID="dff29d23-1ded-43b4-8ae1-5eebb3e30de1"
DOC_CHASSIS_UUID="dff29d23-1ded-43b4-8ae1-5eebb3e30de1"
DOC_NODE_UUID="6d85703a-565d-469a-96ce-30b6de53079d"
DOC_DYNAMIC_NODE_UUID="2b045129-a906-46af-bc1a-092b294b3428"
DOC_PORT_UUID="d2b30520-907d-46c8-bfee-c5586e6fb3a1"
DOC_PORTGROUP_UUID="e43c722c-248e-4c6e-8ce8-0d8ff129387a"
DOC_VOL_CONNECTOR_UUID="9bf93e01-d728-47a3-ad4b-5e66a835037c"
DOC_VOL_TARGET_UUID="bd4d008c-7d31-463d-abf9-6c23d9d55f7f"
DOC_PROVISION_UPDATED_AT="2016-08-18T22:28:49.946416+00:00"
DOC_CREATED_AT="2016-08-18T22:28:48.643434+11:11"
DOC_UPDATED_AT="2016-08-18T22:28:49.653974+00:00"
DOC_IRONIC_CONDUCTOR_HOSTNAME="897ab1dad809"
DOC_ALLOCATION_UUID="3bf138ba-6d71-44e7-b6a1-ca9cac17103e"
DOC_DEPLOY_TEMPLATE_UUID="bbb45f41-d4bc-4307-8d1d-32f95ce1e920"

function GET {
    # GET $RESOURCE
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H "X-OpenStack-Ironic-API-Version: $IRONIC_API_VERSION" \
            ${IRONIC_URL}/$1 | jq -S '.'
}

function POST {
    # POST $RESOURCE $FILENAME
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H "X-OpenStack-Ironic-API-Version: $IRONIC_API_VERSION" \
            -H "Content-Type: application/json" \
            -X POST --data @$2 \
            ${IRONIC_URL}/$1 | jq -S '.'
}

function PATCH {
    # POST $RESOURCE $FILENAME
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H "X-OpenStack-Ironic-API-Version: $IRONIC_API_VERSION" \
            -H "Content-Type: application/json" \
            -X PATCH --data @$2 \
            ${IRONIC_URL}/$1 | jq -S '.'
}

function PUT {
    # PUT $RESOURCE $FILENAME
    curl -s -H "X-Auth-Token: $OS_AUTH_TOKEN" \
            -H "X-OpenStack-Ironic-API-Version: $IRONIC_API_VERSION" \
            -H "Content-Type: application/json" \
            -X PUT --data @$2 \
            ${IRONIC_URL}/$1
}

function wait_for_node_state {
    local node="$1"
    local field="$2"
    local target_state="$3"
    local attempt=10

    while [[ $attempt -gt 0 ]]; do
        res=$(openstack baremetal node show "$node" -f value -c "$field")
        if [[ "$res" == "$target_state" ]]; then
            break
        fi
        sleep 1
        attempt=$((attempt - 1))
        echo "Failed to get node $field == $target_state in $attempt attempts."
    done

    if [[ $attempt == 0 ]]; then
        exit 1
    fi
}

pushd source/samples

###########
# ROOT APIs
GET '' > api-root-response.json

GET 'v1' > api-v1-root-response.json


###########
# DRIVER APIs
GET v1/drivers > drivers-list-response.json
GET v1/drivers?detail=true > drivers-list-detail-response.json
GET v1/drivers/ipmi > driver-get-response.json
GET v1/drivers/agent_ipmitool/properties > driver-property-response.json
GET v1/drivers/agent_ipmitool/raid/logical_disk_properties > driver-logical-disk-properties-response.json


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
POST v1/nodes node-create-request-classic.json > node-create-response.json
NID=$(cat node-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$NID" == "" ]; then
    exit 1
else
    echo "Node created. UUID: $NID"
fi

# Also create a node with a dynamic driver for viewing in the node list
# endpoint
DNID=$(POST v1/nodes node-create-request-dynamic.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$DNID" == "" ]; then
    exit 1
else
    echo "Node created. UUID: $DNID"
fi


# get the list of passthru methods from agent* driver
GET v1/nodes/$NID/vendor_passthru/methods > node-vendor-passthru-response.json

# Change to the fake driver and then move the node into the AVAILABLE
# state without saving any output.
# NOTE that these three JSON files are not included in the docs
PATCH v1/nodes/$NID node-update-driver.json
PUT v1/nodes/$NID/states/provision node-set-manage-state.json
PUT v1/nodes/$NID/states/provision node-set-available-state.json
# Wait node to become available
wait_for_node_state $NID provision_state available

GET v1/nodes/$NID/validate > node-validate-response.json

PUT v1/nodes/$NID/states/power node-set-power-off.json
# Wait node to reach power off state
wait_for_node_state $NID power_state "power off"
GET v1/nodes/$NID/states > node-get-state-response.json

GET v1/nodes > nodes-list-response.json
GET v1/nodes/detail > nodes-list-details-response.json
GET v1/nodes/$NID > node-show-response.json

# Node traits
PUT v1/nodes/$NID/traits node-set-traits-request.json
GET v1/nodes/$NID/traits > node-traits-list-response.json

############
# ALLOCATIONS

POST v1/allocations allocation-create-request.json > allocation-create-response.json
AID=$(cat allocation-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$AID" == "" ]; then
    exit 1
else
    echo "Allocation created. UUID: $AID"
fi

# Create a failed allocation for listing
POST v1/allocations allocation-create-request-2.json

# Poor man's wait_for_allocation
sleep 1

GET v1/allocations > allocations-list-response.json
GET v1/allocations/$AID > allocation-show-response.json
GET v1/nodes/$NID/allocation > node-allocation-show-response.json

############
# NODES - MAINTENANCE

# Do this after allocation API to be able to create successful allocations
PUT v1/nodes/$NID/maintenance node-maintenance-request.json

############
# PORTGROUPS

# Before we can create a portgroup, we must
# write NODE ID into the create request document body
sed -i "s/.*node_uuid.*/    \"node_uuid\": \"$NID\",/" portgroup-create-request.json

POST v1/portgroups portgroup-create-request.json > portgroup-create-response.json
PGID=$(cat portgroup-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$PGID" == "" ]; then
    exit 1
else
    echo "Portgroup created. UUID: $PGID"
fi

GET v1/portgroups > portgroup-list-response.json
GET v1/portgroups/detail > portgroup-list-detail-response.json
PATCH v1/portgroups/$PGID portgroup-update-request.json > portgroup-update-response.json

# skip GET $PGID because same result as POST
# skip DELETE

###########
# PORTS

# Before we can create a port, we must
# write NODE ID and PORTGROUP ID into the create request document body
sed -i "s/.*node_uuid.*/    \"node_uuid\": \"$NID\",/" port-create-request.json
sed -i "s/.*portgroup_uuid.*/    \"portgroup_uuid\": \"$PGID\",/" port-create-request.json

POST v1/ports port-create-request.json > port-create-response.json
PID=$(cat port-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$PID" == "" ]; then
    exit 1
else
    echo "Port created. UUID: $PID"
fi

GET v1/ports > port-list-response.json
GET v1/ports/detail > port-list-detail-response.json
PATCH v1/ports/$PID port-update-request.json > port-update-response.json

# skip GET $PID because same result as POST
# skip DELETE

################
# NODE PORT APIs

GET v1/nodes/$NID/ports > node-port-list-response.json
GET v1/nodes/$NID/ports/detail > node-port-detail-response.json

#####################
# NODE PORTGROUP APIs
GET v1/nodes/$NID/portgroups > node-portgroup-list-response.json
GET v1/nodes/$NID/portgroups/detail > node-portgroup-detail-response.json

#####################
# PORTGROUPS PORT APIs
GET v1/portgroups/$PGID/ports > portgroup-port-list-response.json
GET v1/portgroups/$PGID/ports/detail > portgroup-port-detail-response.json

############
# LOOKUP API

GET v1/lookup?node_uuid=$NID > lookup-node-response.json


#####################
# NODES MANAGEMENT API
# These need to be done while the node is in maintenance mode,
# and the node's driver is "fake", to avoid potential races
# with internal processes that lock the Node

# this corrects an intentional omission in some of the samples
PATCH v1/nodes/$NID node-update-driver-info-request.json > node-update-driver-info-response.json

GET v1/nodes/$NID/management/boot_device/supported > node-get-supported-boot-devices-response.json
PUT v1/nodes/$NID/management/boot_device node-set-boot-device.json
GET v1/nodes/$NID/management/boot_device > node-get-boot-device-response.json

PUT v1/nodes/$NID/management/inject_nmi node-inject-nmi.json

#############################
# NODES VIF ATTACH/DETACH API

POST v1/nodes/$NID/vifs node-vif-attach-request.json
GET v1/nodes/$NID/vifs > node-vif-list-response.json


#############
# VOLUME APIs
GET v1/volume/ > volume-list-response.json

sed -i "s/.*node_uuid.*/    \"node_uuid\": \"$NID\",/" volume-connector-create-request.json
POST v1/volume/connectors volume-connector-create-request.json > volume-connector-create-response.json
VCID=$(cat volume-connector-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$VCID" == "" ]; then
    exit 1
else
    echo "Volume connector created. UUID: $VCID"
fi

GET v1/volume/connectors > volume-connector-list-response.json
GET v1/volume/connectors?detail=True > volume-connector-list-detail-response.json
PATCH v1/volume/connectors/$VCID volume-connector-update-request.json > volume-connector-update-response.json

sed -i "s/.*node_uuid.*/    \"node_uuid\": \"$NID\",/" volume-target-create-request.json
POST v1/volume/targets volume-target-create-request.json > volume-target-create-response.json
VTID=$(cat volume-target-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$VTID" == "" ]; then
    exit 1
else
    echo "Volume target created. UUID: $VCID"
fi

GET v1/volume/targets > volume-target-list-response.json
GET v1/volume/targets?detail=True > volume-target-list-detail-response.json
PATCH v1/volume/targets/$VTID volume-target-update-request.json > volume-target-update-response.json

##################
# NODE VOLUME APIs
GET v1/nodes/$NID/volume > node-volume-list-response.json
GET v1/nodes/$NID/volume/connectors > node-volume-connector-list-response.json
GET v1/nodes/$NID/volume/connectors?detail=True > node-volume-connector-detail-response.json
GET v1/nodes/$NID/volume/targets > node-volume-target-list-response.json
GET v1/nodes/$NID/volume/targets?detail=True > node-volume-target-detail-response.json

##################
# DEPLOY TEMPLATES

POST v1/deploy_templates deploy-template-create-request.json > deploy-template-create-response.json
DTID=$(cat deploy-template-create-response.json | grep '"uuid"' | sed 's/.*"\([0-9a-f\-]*\)",*/\1/')
if [ "$DTID" == "" ]; then
    exit 1
else
    echo "Deploy template created. UUID: $DTID"
fi

GET v1/deploy_templates > deploy-template-list-response.json
GET v1/deploy_templates?detail=True > deploy-template-detail-response.json
GET v1/deploy_templates/$DTID > deploy-template-show-response.json
PATCH v1/deploy_templates/$DTID deploy-template-update-request.json > deploy-template-update-response.json

#####################
# Replace automatically generated UUIDs by already used in documentation
sed -i "s/$BID/$DOC_BIOS_UUID/" *.json
sed -i "s/$CID/$DOC_CHASSIS_UUID/" *.json
sed -i "s/$NID/$DOC_NODE_UUID/" *.json
sed -i "s/$DNID/$DOC_DYNAMIC_NODE_UUID/" *.json
sed -i "s/$PID/$DOC_PORT_UUID/" *.json
sed -i "s/$PGID/$DOC_PORTGROUP_UUID/" *.json
sed -i "s/$VCID/$DOC_VOL_CONNECTOR_UUID/" *.json
sed -i "s/$VTID/$DOC_VOL_TARGET_UUID/" *.json
sed -i "s/$AID/$DOC_ALLOCATION_UUID/" *.json
sed -i "s/$DTID/$DOC_DEPLOY_TEMPLATE_UUID/" *.json
sed -i "s/$(hostname)/$DOC_IRONIC_CONDUCTOR_HOSTNAME/" *.json
sed -i "s/created_at\": \".*\"/created_at\": \"$DOC_CREATED_AT\"/" *.json
sed -i "s/updated_at\": \".*\"/updated_at\": \"$DOC_UPDATED_AT\"/" *.json
sed -i "s/provision_updated_at\": \".*\"/provision_updated_at\": \"$DOC_PROVISION_UPDATED_AT\"/" *.json

##########
# Clean up

openstack baremetal node maintenance set $NID
openstack baremetal node delete $NID
