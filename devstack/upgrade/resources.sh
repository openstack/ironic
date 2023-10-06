#!/bin/bash
#
# Copyright 2015 Hewlett-Packard Development Company, L.P.
# Copyright 2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

set -o errexit

source $GRENADE_DIR/grenaderc
source $GRENADE_DIR/functions

source $TOP_DIR/openrc admin admin

IRONIC_DEVSTACK_DIR=$(cd $(dirname "$0")/.. && pwd)
source $IRONIC_DEVSTACK_DIR/lib/ironic

RESOURCES_NETWORK_GATEWAY=${RESOURCES_NETWORK_GATEWAY:-10.2.0.1}
RESOURCES_FIXED_RANGE=${RESOURCES_FIXED_RANGE:-10.2.0.0/20}
NEUTRON_NET=ironic_grenade

set -o xtrace

# TODO(dtantsur): remove in Rocky, needed for parsing Placement API responses
install_package jq

function wait_for_ironic_resources {
    local i
    local nodes_count
    nodes_count=$(openstack baremetal node list -f value -c "Provisioning State" | wc -l)
    echo_summary "Waiting 5 minutes for Ironic resources become available again"
    for i in $(seq 1 30); do
        if openstack baremetal node list -f value -c "Provisioning State" | grep -qi failed; then
            die $LINENO "One of nodes is in failed state."
        fi
        if [[ $(openstack baremetal node list -f value -c "Provisioning State" | grep -ci available) == $nodes_count ]]; then
            return 0
        fi
        sleep 10
    done
    openstack baremetal node list
    die $LINENO "Timed out waiting for Ironic nodes are available again."
}

total_nodes=$IRONIC_VM_COUNT

if [[ "${HOST_TOPOLOGY}" == "multinode" ]]; then
    total_nodes=$(( 2 * $total_nodes ))
fi

function early_create {
    # We need these steps only in case of flat-network
    if [[ -n "${IRONIC_PROVISION_NETWORK_NAME}" ]]; then
        return
    fi

    # Ironic needs to have network access to the instance during deployment
    # from the control plane (ironic-conductor). This 'early_create' function
    # creates a new network with a unique CIDR, adds a route to this network
    # from ironic-conductor and creates taps between br-int and brbm.
    # ironic-conductor will be able to access the ironic nodes via this new
    # network.
    # TODO(vsaienko) use OSC when Neutron commands are supported in the stable
    # release.
    local net_id
    net_id=$(openstack network create --share $NEUTRON_NET -f value -c id)
    resource_save network net_id $net_id

    local subnet_id
    subnet_id=$(openstack subnet create -f value -c id --ip-version 4 --gateway $RESOURCES_NETWORK_GATEWAY --network $net_id --subnet-range $RESOURCES_FIXED_RANGE $NEUTRON_NET)
    resource_save network subnet_id $subnet_id

    local router_id
    router_id=$(openstack router create $NEUTRON_NET -f value -c id)
    resource_save network router_id $router_id

    openstack router add subnet $NEUTRON_NET $subnet_id
    openstack router set --external-gateway public $NEUTRON_NET

    # Add a route to the baremetal network via the Neutron public router.
    # ironic-conductor will be able to access the ironic nodes via this new
    # route.
    local r_net_gateway
    # Determine the IP address of the interface (ip -4 route get 8.8.8.8) that
    # will be used to access a public IP on the router we created ($router_id).
    # In this case we use the Google DNS server at 8.8.8.8 as the public IP
    # address.  This does not actually attempt to contact 8.8.8.8, it just
    # determines the IP address of the interface that traffic to 8.8.8.8 would
    # use. We use the IP address of this interface to setup the route.
    test_with_retry "sudo ip netns exec qrouter-$router_id ip -4 route get 8.8.8.8 " "Route did not start" 60
    r_net_gateway=$(sudo ip netns exec qrouter-$router_id ip -4 route get 8.8.8.8 |grep dev | awk '{print $7}')
    sudo ip route replace $RESOURCES_FIXED_RANGE via $r_net_gateway

    # NOTE(vsaienko) remove connection between br-int and brbm from old setup
    sudo ovs-vsctl -- --if-exists del-port ovs-1-tap1
    sudo ovs-vsctl -- --if-exists del-port brbm-1-tap1

    create_ovs_taps $net_id
}

function create {
    :
}

function verify {
    :
}

function verify_noapi {
    :
}

function destroy {
    # We need these steps only in case of flat-network
    if [[ -n "${IRONIC_PROVISION_NETWORK_NAME}" ]]; then
        return
    fi

    # NOTE(vsaienko) move ironic VMs back to private network.
    local net_id
    net_id=$(openstack network show private -f value -c id)
    create_ovs_taps $net_id

    # NOTE(vsaienko) during early_create phase we update grenade resources neutron/subnet_id,
    # neutron/router_id, neutron/net_id. It was needed to instruct nova to boot instances
    # in ironic_grenade network instead of neutron_grenade during resources phase. As result
    # during neutron/resources.sh destroy phase ironic_grenade router|subnet|network were deleted.
    # Make sure that we removed neutron resources here.
    openstack router unset --external-gateway neutron_grenade || /bin/true
    openstack router remove subnet neutron_grenade neutron_grenade || /bin/true
    openstack router delete neutron_grenade || /bin/true
    openstack network neutron_grenade || /bin/true
}

# Dispatcher
case $1 in
    "early_create")
        wait_for_ironic_resources
        wait_for_nova_resources $total_nodes
        early_create
        ;;
    "create")
        create
        ;;
    "verify_noapi")
        # NOTE(vdrok): our implementation of verify_noapi is a noop, but
        # grenade always passes the upgrade side (pre-upgrade or post-upgrade)
        # as an argument to it. Pass all the arguments grenade passes further.
        verify_noapi "${@:2}"
        ;;
    "verify")
        # NOTE(vdrok): pass all the arguments grenade passes further.
        verify "${@:2}"
        ;;
    "destroy")
        destroy
        ;;
esac

