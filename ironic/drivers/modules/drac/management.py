# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2017-2018 Dell Inc. or its subsidiaries.
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

import time

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job


drac_exceptions = importutils.try_import('dracclient.exceptions')

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
_CLEAR_JOB_IDS = 'JID_CLEARALL_FORCE'


def _get_boot_device(node, drac_boot_devices=None):
    client = drac_common.get_drac_client(node)

    try:
        boot_modes = client.list_boot_modes()
        next_boot_modes = [mode.id for mode in boot_modes if mode.is_next]
        if _NON_PERSISTENT_BOOT_MODE in next_boot_modes:
            next_boot_mode = _NON_PERSISTENT_BOOT_MODE
        else:
            next_boot_mode = next_boot_modes[0]

        if drac_boot_devices is None:
            drac_boot_devices = client.list_boot_devices()

        # It is possible for there to be no boot device.
        boot_device = None

        if next_boot_mode in drac_boot_devices:
            drac_boot_device = drac_boot_devices[next_boot_mode][0]

            for key, value in _BOOT_DEVICES_MAP.items():
                for id_component in value:
                    if id_component in drac_boot_device.id:
                        boot_device = key
                        break

                if boot_device:
                    break

        return {'boot_device': boot_device,
                'persistent': next_boot_mode != _NON_PERSISTENT_BOOT_MODE}
    except (drac_exceptions.BaseClientException, IndexError) as exc:
        LOG.error('DRAC driver failed to get next boot mode for '
                  'node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


def _get_next_persistent_boot_mode(node):
    client = drac_common.get_drac_client(node)

    try:
        boot_modes = client.list_boot_modes()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get next persistent boot mode for '
                  'node %(node_uuid)s. Reason: %(error)s',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)

    next_persistent_boot_mode = None
    for mode in boot_modes:
        if mode.is_next and mode.id != _NON_PERSISTENT_BOOT_MODE:
            next_persistent_boot_mode = mode.id
            break

    if not next_persistent_boot_mode:
        message = _('List of boot modes, %(list_boot_modes)s, does not '
                    'contain a persistent mode') % {
                        'list_boot_modes': boot_modes}
        LOG.error('DRAC driver failed to get next persistent boot mode for '
                  'node %(node_uuid)s. Reason: %(message)s',
                  {'node_uuid': node.uuid, 'message': message})
        raise exception.DracOperationError(error=message)

    return next_persistent_boot_mode


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


def set_boot_device(node, device, persistent=False):
    """Set the boot device for a node.

    Set the boot device to use on next boot of the node.

    :param node: an ironic node object.
    :param device: the boot device, one of
                   :mod:`ironic.common.boot_devices`.
    :param persistent: Boolean value. True if the boot device will
                       persist to all future boots, False if not.
                       Default: False.
    :raises: DracOperationError on an error from python-dracclient.
    """

    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)

    try:
        drac_boot_devices = client.list_boot_devices()

        current_boot_device = _get_boot_device(node, drac_boot_devices)
        # If we are already booting from the right device, do nothing.
        if current_boot_device == {'boot_device': device,
                                   'persistent': persistent}:
            LOG.debug('DRAC already set to boot from %s', device)
            return

        persistent_boot_mode = _get_next_persistent_boot_mode(node)

        drac_boot_device = None
        for drac_device in drac_boot_devices[persistent_boot_mode]:
            for id_component in _BOOT_DEVICES_MAP[device]:
                if id_component in drac_device.id:
                    drac_boot_device = drac_device.id
                    break

            if drac_boot_device:
                break

        if drac_boot_device:
            if persistent:
                boot_list = persistent_boot_mode
            else:
                boot_list = _NON_PERSISTENT_BOOT_MODE

            client.change_boot_device_order(boot_list, drac_boot_device)
        else:
            # No DRAC boot device of the type requested by the argument
            # 'device' is present. This is normal for UEFI boot mode,
            # following deployment's writing of the operating system to
            # disk. It can also occur when a server has not been
            # powered on after a new boot device has been installed.
            #
            # If the boot order is flexibly programmable, use that to
            # attempt to detect and boot from a device of the requested
            # type during the next boot. That avoids the need for an
            # extra reboot. Otherwise, this function cannot satisfy the
            # request, because it was called with an invalid device.
            bios_settings = client.list_bios_settings(by_name=True)
            if _is_boot_order_flexibly_programmable(persistent, bios_settings):
                drac_boot_mode = bios_settings['BootMode'].current_value
                if drac_boot_mode not in _DRAC_BOOT_MODES:
                    message = _("DRAC reported unknown boot mode "
                                "'%(drac_boot_mode)s'") % {
                                    'drac_boot_mode': drac_boot_mode}
                    LOG.error('DRAC driver failed to change boot device order '
                              'for node %(node_uuid)s. Reason: %(message)s.',
                              {'node_uuid': node.uuid, 'message': message})
                    raise exception.DracOperationError(error=message)

                flexibly_program_settings = _flexibly_program_boot_order(
                    device, drac_boot_mode)
                client.set_bios_settings(flexibly_program_settings)
            else:
                raise exception.InvalidParameterValue(
                    _("set_boot_device called with invalid device "
                      "'%(device)s' for node %(node_id)s.") %
                    {'device': device, 'node_id': node.uuid})

        job_id = client.commit_pending_bios_changes()
        job_entry = client.get_job(job_id)

        timeout = CONF.drac.boot_device_job_status_timeout
        end_time = time.time() + timeout

        LOG.debug('Waiting for BIOS configuration job %{job_id}s '
                  'to be scheduled for node %{node}s',
                  {'job_id': job_id,
                   'node': node.uuid})

        while job_entry.status != "Scheduled":
            if time.time() >= end_time:
                raise exception.DracOperationError(
                    error=_(
                        'Timed out waiting BIOS configuration for job '
                        '%(job)s to reach Scheduled state.  Job is still '
                        'in %(status)s state.') %
                    {'job': job_id, 'status': job_entry.status})
            time.sleep(3)
            job_entry = client.get_job(job_id)

    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to change boot device order for '
                  'node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


class DracManagement(base.ManagementInterface):

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

    @METRICS.timer('DracManagement.validate')
    def validate(self, task):
        """Validate the driver-specific info supplied.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.

        """
        return drac_common.parse_driver_info(task.node)

    @METRICS.timer('DracManagement.get_supported_boot_devices')
    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a TaskManager instance containing the node to act on.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(_BOOT_DEVICES_MAP)

    @METRICS.timer('DracManagement.get_boot_device')
    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Returns the current boot device of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: DracOperationError on an error from python-dracclient.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: whether the boot device will persist to all future
                boots or not, None if it is unknown.
        """
        node = task.node

        boot_device = node.driver_internal_info.get('drac_boot_device')
        if boot_device is not None:
            return boot_device

        return _get_boot_device(node)

    @METRICS.timer('DracManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a TaskManager instance containing the node to act on.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified.
        """
        node = task.node

        if device not in _BOOT_DEVICES_MAP:
            raise exception.InvalidParameterValue(
                _("set_boot_device called with invalid device '%(device)s' "
                  "for node %(node_id)s.") % {'device': device,
                                              'node_id': node.uuid})

        # NOTE(ifarkas): DRAC interface doesn't allow changing the boot device
        #                multiple times in a row without a reboot. This is
        #                because a change need to be committed via a
        #                configuration job, and further configuration jobs
        #                cannot be created until the previous one is processed
        #                at the next boot. As a workaround, saving it to
        #                driver_internal_info and committing the change during
        #                power state change.
        driver_internal_info = node.driver_internal_info
        driver_internal_info['drac_boot_device'] = {'boot_device': device,
                                                    'persistent': persistent}
        node.driver_internal_info = driver_internal_info
        node.save()

    @METRICS.timer('DracManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :returns: returns a consistent format dict of sensor data grouped by
                  sensor type, which can be processed by Ceilometer.
        """
        raise NotImplementedError()

    @METRICS.timer('DracManagement.reset_idrac')
    @base.clean_step(priority=0)
    def reset_idrac(self, task):
        """Reset the iDRAC.

        :param task: a TaskManager instance containing the node to act on.
        :returns: None if it is completed.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        client = drac_common.get_drac_client(node)
        client.reset_idrac(force=True, wait=True)

    @METRICS.timer('DracManagement.known_good_state')
    @base.clean_step(priority=0)
    def known_good_state(self, task):
        """Reset the iDRAC, Clear the job queue.

        :param task: a TaskManager instance containing the node to act on.
        :returns: None if it is completed.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        client = drac_common.get_drac_client(node)
        client.reset_idrac(force=True, wait=True)
        client.delete_jobs(job_ids=[_CLEAR_JOB_IDS])
