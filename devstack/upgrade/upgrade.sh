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

# Keep track of the DevStack directory
IRONIC_DEVSTACK_DIR=$(dirname "$0")/..
source $IRONIC_DEVSTACK_DIR/lib/ironic

# Print the commands being run so that we can see the command that triggers
# an error.  It is also useful for following allowing as the install occurs.
set -o xtrace

function is_nova_migration {
    # Deterine whether we're "upgrading" from another compute driver
    _ironic_old_driver=$(source $BASE_DEVSTACK_DIR/functions; source $BASE_DEVSTACK_DIR/localrc; echo $VIRT_DRIVER)
    [ "$_ironic_old_driver" != "ironic" ]
}

# Duplicate all required devstack setup that is needed before starting
# Ironic during a sideways upgrade, where we are migrating from an
# devstack environment without Ironic.
function init_ironic {
    # We need to source credentials here but doing so in the gate will unset
    # HOST_IP.
    local tmp_host_ip=$HOST_IP
    source $TARGET_DEVSTACK_DIR/openrc admin admin
    HOST_IP=$tmp_host_ip
    IRONIC_BAREMETAL_BASIC_OPS="True"
    $TARGET_DEVSTACK_DIR/tools/install_prereqs.sh
    initialize_database_backends
    recreate_database ironic utf8
    install_nova_hypervisor
    configure_nova_hypervisor
    configure_ironic_dirs
    create_ironic_cache_dir
    configure_ironic
    create_ironic_accounts
    configure_tftpd
    configure_iptables
    configure_ironic_auxiliary
    upload_baremetal_ironic_deploy
    stop_nova_compute || true
    start_nova_compute
}

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

# If we are sideways upgrading and migrating from a base deployed /w
# VIRT_DRIVER=fake, we need to run Ironic install, config and init
# code from devstac.
if is_nova_migration ; then
    init_ironic
fi

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
ensure_services_started ironic-api ironic-conductor
ensure_logs_exist ir-cond ir-api

set +o xtrace
echo "*********************************************************************"
echo "SUCCESS: End $0"
echo "*********************************************************************"
