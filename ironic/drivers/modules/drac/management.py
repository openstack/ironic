# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
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
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _, _LE
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job

drac_exceptions = importutils.try_import('dracclient.exceptions')

LOG = logging.getLogger(__name__)

_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'HardDisk',
    boot_devices.PXE: 'NIC',
    boot_devices.CDROM: 'Optical',
}

# BootMode constants
PERSISTENT_BOOT_MODE = 'IPL'
NON_PERSISTENT_BOOT_MODE = 'OneTime'


def _get_boot_device(node, drac_boot_devices=None):
    client = drac_common.get_drac_client(node)

    try:
        boot_modes = client.list_boot_modes()
        next_boot_modes = [mode.id for mode in boot_modes if mode.is_next]
        if NON_PERSISTENT_BOOT_MODE in next_boot_modes:
            next_boot_mode = NON_PERSISTENT_BOOT_MODE
        else:
            next_boot_mode = next_boot_modes[0]

        if drac_boot_devices is None:
            drac_boot_devices = client.list_boot_devices()
        drac_boot_device = drac_boot_devices[next_boot_mode][0]

        boot_device = next(key for (key, value) in _BOOT_DEVICES_MAP.items()
                           if value in drac_boot_device.id)
        return {'boot_device': boot_device,
                'persistent': next_boot_mode == PERSISTENT_BOOT_MODE}
    except (drac_exceptions.BaseClientException, IndexError) as exc:
        LOG.error(_LE('DRAC driver failed to get next boot mode for '
                      'node %(node_uuid)s. Reason: %(error)s.'),
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


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

        drac_boot_device = next(drac_device.id for drac_device
                                in drac_boot_devices[PERSISTENT_BOOT_MODE]
                                if _BOOT_DEVICES_MAP[device] in drac_device.id)

        if persistent:
            boot_list = PERSISTENT_BOOT_MODE
        else:
            boot_list = NON_PERSISTENT_BOOT_MODE

        client.change_boot_device_order(boot_list, drac_boot_device)
        client.commit_pending_bios_changes()
    except drac_exceptions.BaseClientException as exc:
        LOG.error(_LE('DRAC driver failed to change boot device order for '
                      'node %(node_uuid)s. Reason: %(error)s.'),
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


class DracManagement(base.ManagementInterface):

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

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

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a TaskManager instance containing the node to act on.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(_BOOT_DEVICES_MAP.keys())

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

    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :returns: returns a consistent format dict of sensor data grouped by
                  sensor type, which can be processed by Ceilometer.
        """
        raise NotImplementedError()
