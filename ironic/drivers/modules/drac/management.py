# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2017-2021 Dell Inc. or its subsidiaries.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
DRAC management interface
"""

from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import metrics_utils
from ironic.common import states
from ironic.drivers import base
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import management as redfish_management
from ironic.drivers.modules.redfish import utils as redfish_utils


LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

# This dictionary is used to map boot device names between two (2) name
# spaces. The name spaces are:
#
#     1) ironic boot devices
#     2) iDRAC boot sources
#
# Mapping can be performed in both directions.
#
# The keys are ironic boot device types. Each value is a list of strings
# that appear in the identifiers of iDRAC boot sources.
#
# The iDRAC represents boot sources with class DCIM_BootSourceSetting
# [1]. Each instance of that class contains a unique identifier, which
# is called an instance identifier, InstanceID,
#
# An InstanceID contains the Fully Qualified Device Descriptor (FQDD) of
# the physical device that hosts the boot source [2].
#
# [1] "Dell EMC BIOS and Boot Management Profile", Version 4.0.0, July
#     10, 2017, Section 7.2 "Boot Management", pp. 44-47 --
#     http://en.community.dell.com/techcenter/extras/m/white_papers/20444495/download
# [2] "Lifecycle Controller Version 3.15.15.15 User's Guide", Dell EMC,
#     2017, Table 13, "Easy-to-use Names of System Components", pp. 71-74 --
#     http://topics-cdn.dell.com/pdf/idrac9-lifecycle-controller-v3.15.15.15_users-guide2_en-us.pdf
_BOOT_DEVICES_MAP = {
    boot_devices.DISK: ['AHCI', 'Disk', 'RAID'],
    boot_devices.PXE: ['NIC'],
    boot_devices.CDROM: ['Optical'],
}

_DRAC_BOOT_MODES = ['Bios', 'Uefi']

# BootMode constant
_NON_PERSISTENT_BOOT_MODE = 'OneTime'

# Clear job id's constant
_CLEAR_JOB_IDS = 'JID_CLEARALL'

# Clean steps constant
_CLEAR_JOBS_CLEAN_STEPS = ['clear_job_queue', 'known_good_state']


def _is_boot_order_flexibly_programmable(persistent, bios_settings):
    return persistent and 'SetBootOrderFqdd1' in bios_settings


def _flexibly_program_boot_order(device, drac_boot_mode):
    if device == boot_devices.DISK:
        if drac_boot_mode == 'Bios':
            bios_settings = {'SetBootOrderFqdd1': 'HardDisk.List.1-1'}
        else:
            # 'Uefi'
            bios_settings = {
                'SetBootOrderFqdd1': '*.*.*',  # Disks, which are all else
                'SetBootOrderFqdd2': 'NIC.*.*',
                'SetBootOrderFqdd3': 'Optical.*.*',
                'SetBootOrderFqdd4': 'Floppy.*.*',
            }
    elif device == boot_devices.PXE:
        bios_settings = {'SetBootOrderFqdd1': 'NIC.*.*'}
    else:
        # boot_devices.CDROM
        bios_settings = {'SetBootOrderFqdd1': 'Optical.*.*'}

    return bios_settings


class DracRedfishManagement(redfish_management.RedfishManagement):
    """iDRAC Redfish interface for management-related actions."""

    @METRICS.timer('DracRedfishManagement.clear_job_queue')
    @base.verify_step(priority=0)
    @base.clean_step(priority=0, requires_ramdisk=False)
    def clear_job_queue(self, task):
        """Clear iDRAC job queue.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        try:
            drac_utils.execute_oem_manager_method(
                task, 'clear job queue',
                lambda m: m.job_service.delete_jobs(job_ids=['JID_CLEARALL']))
        except exception.RedfishError as exc:
            if "Oem/Dell/DellJobService is missing" in str(exc):
                LOG.warning('iDRAC on node %(node)s does not support '
                            'clearing Lifecycle Controller job queue '
                            'using the idrac-redfish driver. '
                            'If using iDRAC9, consider upgrading firmware.',
                            {'node': task.node.uuid})
            if task.node.provision_state != states.VERIFYING:
                raise

    @METRICS.timer('DracRedfishManagement.reset_idrac')
    @base.verify_step(priority=0)
    @base.clean_step(priority=0, requires_ramdisk=False)
    def reset_idrac(self, task):
        """Reset the iDRAC.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        try:
            drac_utils.execute_oem_manager_method(
                task, 'reset iDRAC', lambda m: m.reset_idrac())
            redfish_utils.wait_until_get_system_ready(task.node)
            LOG.info('Reset iDRAC for node %(node)s done',
                     {'node': task.node.uuid})
        except exception.RedfishError as exc:
            if "Oem/Dell/DelliDRACCardService is missing" in str(exc):
                LOG.warning('iDRAC on node %(node)s does not support '
                            'iDRAC reset using the idrac-redfish driver. '
                            'If using iDRAC9, consider upgrading firmware. ',
                            {'node': task.node.uuid})
            if task.node.provision_state != states.VERIFYING:
                raise

    @METRICS.timer('DracRedfishManagement.known_good_state')
    @base.verify_step(priority=0)
    @base.clean_step(priority=0, requires_ramdisk=False)
    def known_good_state(self, task):
        """Reset iDRAC to known good state.

        An iDRAC is reset to a known good state by resetting it and
        clearing its job queue.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        self.reset_idrac(task)
        self.clear_job_queue(task)
        LOG.info('Reset iDRAC to known good state for node %(node)s',
                 {'node': task.node.uuid})
