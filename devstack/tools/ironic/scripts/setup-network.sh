#!/usr/bin/env bash

# **setup-network**

# Setups openvswitch libvirt network suitable for
# running baremetal poseur nodes for ironic testing purposes

set -exu

# Make tracing more educational
export PS4='+ ${BASH_SOURCE:-}:${FUNCNAME[0]:-}:L${LINENO:-}:   '

LIBVIRT_CONNECT_URI=${LIBVIRT_CONNECT_URI:-"qemu:///system"}

# Keep track of the DevStack directory
TOP_DIR=$(cd $(dirname "$0")/.. && pwd)
BRIDGE_NAME=${1:-brbm}
PUBLIC_BRIDGE_MTU=${2:-1500}

export VIRSH_DEFAULT_CONNECT_URI="$LIBVIRT_CONNECT_URI"

# Only add bridge if missing. Bring it UP.
(sudo ovs-vsctl list-br | grep ${BRIDGE_NAME}) || sudo ovs-vsctl add-br ${BRIDGE_NAME}
sudo ip link set dev ${BRIDGE_NAME} up

# Remove bridge before replacing it.
(virsh net-list | grep "${BRIDGE_NAME} ") && virsh net-destroy ${BRIDGE_NAME}
(virsh net-list --inactive  | grep "${BRIDGE_NAME} ") && virsh net-undefine ${BRIDGE_NAME}

virsh net-define <(sed s/brbm/$BRIDGE_NAME/ $TOP_DIR/templates/brbm.xml)
virsh net-autostart ${BRIDGE_NAME}
virsh net-start ${BRIDGE_NAME}

sudo ip link set dev ${BRIDGE_NAME} mtu $PUBLIC_BRIDGE_MTU
