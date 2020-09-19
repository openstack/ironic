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

source $TOP_DIR/openrc admin admin

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

# calls upgrade-ironic for specific release
upgrade_project ironic $RUN_DIR $BASE_DEVSTACK_BRANCH $TARGET_DEVSTACK_BRANCH

# NOTE(rloo): make sure it is OK to do an upgrade. Except that we aren't
# parsing/checking the output of this command because the output could change
# based on the checks it makes.
$IRONIC_BIN_DIR/ironic-status upgrade check

$IRONIC_BIN_DIR/ironic-dbsync --config-file=$IRONIC_CONF_FILE

# NOTE(vsaienko) pin_release only on multinode job, for cold upgrade (single node)
# run online data migration instead.
if [[ "${HOST_TOPOLOGY}" == "multinode" ]]; then
    iniset $IRONIC_CONF_FILE DEFAULT pin_release_version ${BASE_DEVSTACK_BRANCH#*/}
else
    ironic-dbsync online_data_migrations
fi

ensure_started='ironic-conductor nova-compute '
ensure_stopped=''
# Multinode grenade is designed to upgrade services only on primary node. And there is no way to manipulate
# subnode during grenade phases. With this after upgrade we can have upgraded (new) services on primary
# node and not upgraded (old) services on subnode.
# According to Ironic upgrade procedure, we shouldn't have upgraded (new) ironic-api and not upgraded (old)
# ironic-conductor. By setting redirect of API requests from primary node to subnode during upgrade
# allow to satisfy ironic upgrade requirements.
if [[ "$HOST_TOPOLOGY_ROLE" == "primary" ]]; then
    disable_service ir-api
    ensure_stopped+='ironic-api'
    ironic_wsgi_conf=$(apache_site_config_for ironic-api-wsgi)
    sudo cp $IRONIC_DEVSTACK_FILES_DIR/apache-ironic-api-redirect.template $ironic_wsgi_conf
    sudo sed -e "
        s|%IRONIC_SERVICE_PROTOCOL%|$IRONIC_SERVICE_PROTOCOL|g;
        s|%IRONIC_SERVICE_HOST%|$IRONIC_PROVISION_SUBNET_SUBNODE_IP|g;
    " -i $ironic_wsgi_conf
    enable_apache_site ipxe-ironic
    restart_apache_server
else
    ensure_started+='ironic-api '
fi

start_ironic

# NOTE(vsaienko) do not restart n-cpu on multinode as we didn't upgrade nova.
if [[ "${HOST_TOPOLOGY}" != "multinode" ]]; then
    # NOTE(vsaienko) installing ironic service triggers apache restart, that
    # may cause nova-compute failure due to LP1537076
    stop_nova_compute || true
    wait_for_keystone
    start_nova_compute
fi

if [[ -n "$ensure_stopped" ]]; then
    ensure_services_stopped $ensure_stopped
fi

ensure_services_started $ensure_started

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
