#!/usr/bin/env bash

# ``upgrade-ironic``

echo "*********************************************************************"
echo "Begin $0"
echo "*********************************************************************"

# Clean up any resources that may be in use
cleanup() {
    set +o errexit

    echo "*********************************************************************"
    echo "ERROR: Abort $0"
    echo "*********************************************************************"

    # Kill ourselves to signal any calling process
    trap 2; kill -2 $$
}

trap cleanup SIGHUP SIGINT SIGTERM

# Keep track of the grenade directory
RUN_DIR=$(cd $(dirname "$0") && pwd)

# Source params
source $GRENADE_DIR/grenaderc

source $TOP_DIR/openrc admin admin

# Import common functions
source $GRENADE_DIR/functions

# This script exits on an error so that errors don't compound and you see
# only the first error that occurred.
set -o errexit

# Upgrade Ironic
# ============

# Duplicate some setup bits from target DevStack
source $TARGET_DEVSTACK_DIR/stackrc
source $TARGET_DEVSTACK_DIR/lib/tls
source $TARGET_DEVSTACK_DIR/lib/nova
source $TARGET_DEVSTACK_DIR/lib/neutron-legacy
source $TARGET_DEVSTACK_DIR/lib/apache
source $TARGET_DEVSTACK_DIR/lib/keystone

# Keep track of the DevStack directory
IRONIC_DEVSTACK_DIR=$(dirname "$0")/..
source $IRONIC_DEVSTACK_DIR/lib/ironic

# Print the commands being run so that we can see the command that triggers
# an error.  It is also useful for following allowing as the install occurs.
set -o xtrace


function wait_for_keystone {
    if ! wait_for_service $SERVICE_TIMEOUT ${KEYSTONE_AUTH_URI}/v$IDENTITY_API_VERSION/; then
        die $LINENO "keystone did not start"
    fi
}

# Save current config files for posterity
if  [[ -d $IRONIC_CONF_DIR ]] && [[ ! -d $SAVE_DIR/etc.ironic ]] ; then
    cp -pr $IRONIC_CONF_DIR $SAVE_DIR/etc.ironic
fi

stack_install_service ironic

$IRONIC_BIN_DIR/ironic-dbsync --config-file=$IRONIC_CONF_FILE

# calls upgrade-ironic for specific release
upgrade_project ironic $RUN_DIR $BASE_DEVSTACK_BRANCH $TARGET_DEVSTACK_BRANCH

start_ironic

# NOTE(vsaienko) installing ironic service triggers apache restart, that
# may cause nova-compute failure due to LP1537076
stop_nova_compute || true
wait_for_keystone
start_nova_compute

# Don't succeed unless the services come up
logs_exist="ir-cond"

if [[ "$IRONIC_USE_MOD_WSGI" != "True" ]]; then
    logs_exist+=" ir-api"
fi

ensure_services_started ironic-api ironic-conductor
ensure_logs_exist $logs_exist

# We need these steps only in case of flat-network
# NOTE(vsaienko) starting from Ocata when Neutron is restarted there is no guarantee that
# internal tag, that was assigned to network will be the same. As result we need to update
# tag on link between br-int and brbm to new value after restart.
if [[ -z "${IRONIC_PROVISION_NETWORK_NAME}" ]]; then
    net_id=$(openstack network show ironic_grenade -f value -c id)
    create_ovs_taps $net_id
fi

set +o xtrace
echo "*********************************************************************"
echo "SUCCESS: End $0"
echo "*********************************************************************"
