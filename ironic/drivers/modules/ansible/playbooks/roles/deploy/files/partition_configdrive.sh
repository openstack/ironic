#!/bin/sh

# Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# NOTE(pas-ha) this is mostly copied over from Ironic Python Agent
# compared to the original file in IPA,

# TODO(pas-ha) rewrite this shell script to be a proper Ansible module

# This should work with almost any image that uses MBR partitioning and
# doesn't already have 3 or more partitions -- or else you'll no longer
# be able to create extended partitions on the disk.

# Takes one argument - block device

log() {
    echo "`basename $0`: $@"
}

fail() {
    log "Error: $@"
    exit 1
}

MAX_DISK_PARTITIONS=128
MAX_MBR_SIZE_MB=2097152

DEVICE="$1"

[ -b $DEVICE ] || fail "(DEVICE) $DEVICE is not a block device"

# We need to run partx -u to ensure all partitions are visible so the
# following blkid command returns partitions just imaged to the device
partx -u $DEVICE  || fail "running partx -u $DEVICE"

# todo(jayf): partx -u doesn't work in all cases, but partprobe fails in
# devstack. We run both commands now as a temporary workaround for bug 1433812
# long term, this should all be refactored into python and share code with
# the other partition-modifying code in the agent.
partprobe $DEVICE || true

# Check for preexisting partition for configdrive
EXISTING_PARTITION=`/sbin/blkid -l -o device $DEVICE -t LABEL=config-2`
if [ -z $EXISTING_PARTITION ]; then
    # Check if it is GPT partition and needs to be re-sized
    if [ `partprobe $DEVICE print 2>&1 | grep "fix the GPT to use all of the space"` ]; then
        log "Fixing GPT to use all of the space on device $DEVICE"
        sgdisk -e $DEVICE || fail "move backup GPT data structures to the end of ${DEVICE}"

        # Need to create new partition for config drive
        # Not all images have partion numbers in a sequential numbers. There are holes.
        # These holes get filled up when a new partition is created.
        TEMP_DIR="$(mktemp -d)"
        EXISTING_PARTITION_LIST=$TEMP_DIR/existing_partitions
        UPDATED_PARTITION_LIST=$TEMP_DIR/updated_partitions

        gdisk -l $DEVICE | grep -A$MAX_DISK_PARTITIONS "Number  Start" | grep -v "Number  Start" > $EXISTING_PARTITION_LIST

        # Create small partition at the end of the device
        log "Adding configdrive partition to $DEVICE"
        sgdisk -n 0:-64MB:0 $DEVICE || fail "creating configdrive on ${DEVICE}"

        gdisk -l $DEVICE | grep -A$MAX_DISK_PARTITIONS "Number  Start" | grep -v "Number  Start" > $UPDATED_PARTITION_LIST

        CONFIG_PARTITION_ID=`diff $EXISTING_PARTITION_LIST $UPDATED_PARTITION_LIST | tail -n1 |awk '{print $2}'`
        ISO_PARTITION="${DEVICE}${CONFIG_PARTITION_ID}"
    else
        log "Working on MBR only device $DEVICE"

        # get total disk size, to detect if that exceeds 2TB msdos limit
        disksize_bytes=$(blockdev --getsize64 $DEVICE)
        disksize_mb=$(( ${disksize_bytes%% *} / 1024 / 1024))

        startlimit=-64MiB
        endlimit=-0
        if [ "$disksize_mb" -gt "$MAX_MBR_SIZE_MB" ]; then
            # Create small partition at 2TB limit
            startlimit=$(($MAX_MBR_SIZE_MB - 65))
            endlimit=$(($MAX_MBR_SIZE_MB - 1))
        fi

        log "Adding configdrive partition to $DEVICE"
        parted -a optimal -s -- $DEVICE mkpart primary fat32 $startlimit $endlimit || fail "creating configdrive on ${DEVICE}"

        # Find partition we just created
        # Dump all partitions, ignore empty ones, then get the last partition ID
        ISO_PARTITION=`sfdisk --dump $DEVICE | grep -v ' 0,' | tail -n1 | awk -F ':' '{print $1}' | sed -e 's/\s*$//'` || fail "finding ISO partition created on ${DEVICE}"

        # Wait for udev to pick up the partition
        udevadm settle --exit-if-exists=$ISO_PARTITION
    fi
else
    log "Existing configdrive found on ${DEVICE} at ${EXISTING_PARTITION}"
    ISO_PARTITION=$EXISTING_PARTITION
fi

# Output the created/discovered partition for configdrive
echo "configdrive $ISO_PARTITION"
