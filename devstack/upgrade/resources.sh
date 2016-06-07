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


function early_create {
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

    local subnet_params=""
    subnet_params+="--ip_version 4 "
    subnet_params+="--gateway $RESOURCES_NETWORK_GATEWAY "
    subnet_params+="--name $NEUTRON_NET "
    subnet_params+="$net_id $RESOURCES_FIXED_RANGE"

    local subnet_id
    subnet_id=$(neutron subnet-create $subnet_params | grep ' id ' | get_field 2)
    resource_save network subnet_id $subnet_id

    local router_id
    router_id=$(openstack router create $NEUTRON_NET -f value -c id)
    resource_save network router_id $router_id

    neutron router-interface-add $NEUTRON_NET $subnet_id
    neutron router-gateway-set $NEUTRON_NET public

    # NOTE(vsaeinko) sleep is needed in order to setup route
    sleep 5

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
    r_net_gateway=$(sudo ip netns exec qrouter-$router_id ip -4 route get 8.8.8.8 |grep dev | awk '{print $7}')
    sudo ip route replace $RESOURCES_FIXED_RANGE via $r_net_gateway

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
    :
}

# Dispatcher
case $1 in
    "early_create")
        early_create
        ;;
    "create")
        create
        ;;
    "verify_noapi")
        verify_noapi
        ;;
    "verify")
        verify
        ;;
    "destroy")
        destroy
        ;;
    "force_destroy")
        set +o errexit
        destroy
        ;;
esac

