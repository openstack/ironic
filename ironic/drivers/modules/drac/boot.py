# Copyright 2019 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2019-2021 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)

sushy = importutils.try_import('sushy')


class DracRedfishVirtualMediaBoot(redfish_boot.RedfishVirtualMediaBoot):
    """iDRAC Redfish interface for virtual media boot-related actions.

    Virtual Media allows booting the system from "virtual"
    CD/DVD drive containing user image that BMC "inserts"
    into the drive.

    The CD/DVD images must be in ISO format and (depending on
    BMC implementation) could be pulled over HTTP, served as
    iSCSI targets or NFS volumes.

    The baseline boot workflow is mostly based on the standard
    Redfish virtual media boot interface, which looks like
    this:

    1. Pull kernel, ramdisk and ESP if UEFI boot is requested (FAT partition
       image with EFI boot loader) images
    2. Create bootable ISO out of images (#1), push it to Glance and
       pass to the BMC as Swift temporary URL
    3. Optionally create floppy image with desired system configuration data,
       push it to Glance and pass to the BMC as Swift temporary URL
    4. Insert CD/DVD and (optionally) floppy images and set proper boot mode

    For building deploy or rescue ISO, redfish boot interface uses
    `deploy_kernel`/`deploy_ramdisk` or `rescue_kernel`/`rescue_ramdisk`
    properties from `[instance_info]` or `[driver_info]`.

    For building boot (user) ISO, redfish boot interface seeks `kernel_id`
    and `ramdisk_id` properties in the Glance image metadata found in
    `[instance_info]image_source` node property.

    iDRAC virtual media boot interface only differs by the way how it
    sets the node to boot from a virtual media device - this is done
    via OEM action call implemented in Dell sushy OEM extension package.
    """

    if sushy:
        VIRTUAL_MEDIA_DEVICES = {
            boot_devices.FLOPPY: sushy.VIRTUAL_MEDIA_FLOPPY,
            boot_devices.CDROM: sushy.VIRTUAL_MEDIA_CD
        }

    def _validate_vendor(self, task, managers):
        pass  # assume people are doing the right thing

    @classmethod
    def _set_boot_device(cls, task, device, persistent=False):
        """Set boot device for a node.

        Dell iDRAC Redfish implementation does not support setting
        boot device to virtual media via standard Redfish means.
        Instead, Dell BMC sets boot device to local physical CD/floppy.
        However, it is still feasible to boot from a virtual media
        device by invoking Dell OEM extension.

        :param task: a TaskManager instance.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Whether to set next-boot, or make the change
            permanent. Default: False.
        :raises: InvalidParameterValue if the validation of the
            ManagementInterface fails.
        """
        # NOTE(etingof): always treat CD/floppy as virtual
        if device not in cls.VIRTUAL_MEDIA_DEVICES:
            LOG.debug(
                'Treating boot device %(device)s as a non-virtual '
                'media device for node %(node)s',
                {'device': device, 'node': task.node.uuid})
            super(DracRedfishVirtualMediaBoot, cls)._set_boot_device(
                task, device, persistent)
            return

        device = cls.VIRTUAL_MEDIA_DEVICES[device]

        system = redfish_utils.get_system(task.node)

        drac_utils.execute_oem_manager_method(
            task, 'set virtual boot device',
            lambda m, manager: m.set_virtual_boot_device(
                device, persistent=persistent, system=system,
                manager=manager), pass_manager=True)
