#!/usr/bin/env bash

# **create-nodes**

# Creates baremetal poseur nodes for ironic testing purposes

set -ex

# Keep track of the DevStack directory
TOP_DIR=$(cd $(dirname "$0")/.. && pwd)

NAME=$1
CPU=$2
MEM=$(( 1024 * $3 ))
# Extra G to allow fuzz for partition table : flavor size and registered size
# need to be different to actual size.
DISK=$(( $4 + 1))
ARCH=$5
BRIDGE=$6
EMULATOR=$7
VBMC_PORT=$8
LOGDIR=$9
DISK_FORMAT=${10}

LIBVIRT_NIC_DRIVER=${LIBVIRT_NIC_DRIVER:-"virtio"}
LIBVIRT_STORAGE_POOL=${LIBVIRT_STORAGE_POOL:-"default"}
LIBVIRT_CONNECT_URI=${LIBVIRT_CONNECT_URI:-"qemu:///system"}

export VIRSH_DEFAULT_CONNECT_URI=$LIBVIRT_CONNECT_URI

if ! virsh pool-list --all | grep -q $LIBVIRT_STORAGE_POOL; then
    virsh pool-define-as --name $LIBVIRT_STORAGE_POOL dir --target /var/lib/libvirt/images >&2
    virsh pool-autostart $LIBVIRT_STORAGE_POOL >&2
    virsh pool-start $LIBVIRT_STORAGE_POOL >&2
fi

pool_state=$(virsh pool-info $LIBVIRT_STORAGE_POOL | grep State | awk '{ print $2 }')
if [ "$pool_state" != "running" ] ; then
    [ ! -d /var/lib/libvirt/images ] && sudo mkdir /var/lib/libvirt/images
    virsh pool-start $LIBVIRT_STORAGE_POOL >&2
fi

if [ -n "$LOGDIR" ] ; then
    mkdir -p "$LOGDIR"
fi

PREALLOC=
if [ -f /etc/debian_version -a "$DISK_FORMAT" == "qcow2" ]; then
    PREALLOC="--prealloc-metadata"
fi

if [ -n "$LOGDIR" ] ; then
    VM_LOGGING="--console-log $LOGDIR/${NAME}_console.log"
else
    VM_LOGGING=""
fi
VOL_NAME="${NAME}.${DISK_FORMAT}"

if ! virsh list --all | grep -q $NAME; then
    virsh vol-list --pool $LIBVIRT_STORAGE_POOL | grep -q $VOL_NAME &&
        virsh vol-delete $VOL_NAME --pool $LIBVIRT_STORAGE_POOL >&2
    virsh vol-create-as $LIBVIRT_STORAGE_POOL ${VOL_NAME} ${DISK}G --format $DISK_FORMAT $PREALLOC >&2
    volume_path=$(virsh vol-path --pool $LIBVIRT_STORAGE_POOL $VOL_NAME)
    # Pre-touch the VM to set +C, as it can only be set on empty files.
    sudo touch "$volume_path"
    sudo chattr +C "$volume_path" || true
    $TOP_DIR/scripts/configure-vm.py \
        --bootdev network --name $NAME --image "$volume_path" \
        --arch $ARCH --cpus $CPU --memory $MEM --libvirt-nic-driver $LIBVIRT_NIC_DRIVER \
        --emulator $EMULATOR --network $BRIDGE --disk-format $DISK_FORMAT $VM_LOGGING >&2

    # Createa Virtual BMC for the node if IPMI is used
    if [[ $(type -P vbmc) != "" ]]; then
        vbmc add $NAME --port $VBMC_PORT
        vbmc start $NAME
    fi
fi

# echo mac
VM_MAC=$(virsh dumpxml $NAME | grep "mac address" | head -1 | cut -d\' -f2)
echo $VM_MAC $VBMC_PORT
